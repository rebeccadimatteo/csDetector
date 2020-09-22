import sys, getopt, os, subprocess, shutil
import git
import yaml
import pkg_resources
import sentistrength

from configuration import Configuration
from repoLoader import getRepo
from aliasWorker import replaceAliases
from commitAnalysis import commitAnalysis
import centralityAnalysis as centrality
from tagAnalysis import tagAnalysis
from devAnalysis import devAnalysis
from graphqlAnalysis.releaseAnalysis import releaseAnalysis
from graphqlAnalysis.prAnalysis import prAnalysis
from graphqlAnalysis.issueAnalysis import issueAnalysis
from dateutil.relativedelta import relativedelta

FILEBROWSER_PATH = os.path.join(os.getenv("WINDIR"), "explorer.exe")


def main(argv):
    try:
        # validate running in venv
        if not hasattr(sys, "prefix"):
            raise Exception(
                "The tool does not appear to be running in the virtual environment!\nSee README for activation."
            )

        # validate python version
        if sys.version_info.major != 3 or sys.version_info.minor != 8:
            raise Exception(
                "Expected Python 3.8 as runtime but got {0}.{1}, the tool might not run as expected!\nSee README for stack requirements.".format(
                    sys.version_info.major,
                    sys.version_info.minor,
                    sys.version_info.micro,
                )
            )

        # validate installed modules
        required = {
            "wheel",
            "networkx",
            "matplotlib",
            "gitpython",
            "requests",
            "pyyaml",
            "progress",
            "strsimpy",
            "python-dateutil",
            "sentistrength",
        }
        installed = {pkg for pkg in pkg_resources.working_set.by_key}
        missing = required - installed

        if len(missing) > 0:
            raise Exception(
                "Missing required modules: {0}.\nSee README for tool installation.".format(
                    missing
                )
            )

        # parse args
        configFile = ""
        pat = ""

        try:
            opts, args = getopt.getopt(argv, "hc:p:", ["help", "config=", "pat="])
        except getopt.GetoptError:
            raise Exception(
                "Incorrect arguments!\nmain.py -c <config.yml> -p <GitHub PAT>"
            )
        for opt, arg in opts:
            if opt in ("-h", "--help"):
                print("main.py -c <config.yml> -p <GitHub PAT>")
                sys.exit()
            elif opt in ("-c", "--config"):
                configFile = arg
            elif opt in ("-p", "--pat"):
                pat = arg

        # validate file
        if not os.path.exists(configFile):
            raise Exception("Configuration file not found")

        # read configuration
        config = ...  # type: Configuration
        with open(configFile, "r", encoding="utf-8-sig") as file:
            content = file.read()
            config = yaml.load(content, Loader=yaml.FullLoader)

        # get repository reference
        repo = getRepo(config)

        # delete any existing output files for repo
        if os.path.exists(config.analysisOutputPath):
            shutil.rmtree(config.analysisOutputPath, False)

        os.makedirs(config.analysisOutputPath)

        # setup sentiment analysis
        senti = sentistrength.PySentiStr()
        senti.setSentiStrengthPath(config.sentiStrengthJarPath)
        senti.setSentiStrengthLanguageFolderPath(config.sentiStrengthDataPath)

        # prepare batch delta
        delta = relativedelta(months=+config.batchSizeInMonths)

        # handle aliases
        commits = list(replaceAliases(repo.iter_commits(), config.aliasPath))

        # run analysis
        batchDates, authorInfoDict = commitAnalysis(
            senti, commits, delta, config.analysisOutputPath
        )

        tagAnalysis(repo, delta, batchDates, config.analysisOutputPath)

        centrality.centralityAnalysis(
            commits, delta, batchDates, config.analysisOutputPath
        )

        releaseAnalysis(
            commits,
            pat,
            config.repositoryShortname,
            delta,
            batchDates,
            config.analysisOutputPath,
        )

        prParticipantBatches = prAnalysis(
            config,
            pat,
            senti,
            delta,
            batchDates,
        )

        issueParticipantBatches = issueAnalysis(
            config,
            pat,
            senti,
            delta,
            batchDates,
        )

        for batchIdx, batchDate in enumerate(batchDates):

            # get combined author lists
            combinedAuthorsInBatch = (
                prParticipantBatches[batchIdx] + issueParticipantBatches[batchIdx]
            )

            # build combined network
            centrality.buildGraphQlNetwork(
                batchIdx, combinedAuthorsInBatch, "Combined", config.analysisOutputPath
            )

            # get combined unique authors for both PRs and issues
            uniqueAuthorsInPrBatch = set(
                author for pr in prParticipantBatches[batchIdx] for author in pr
            )

            uniqueAuthorsInIssueBatch = set(
                author for pr in issueParticipantBatches[batchIdx] for author in pr
            )

            uniqueAuthorsInBatch = uniqueAuthorsInPrBatch.union(
                uniqueAuthorsInIssueBatch
            )

            # run dev analysis
            devAnalysis(
                authorInfoDict,
                batchIdx,
                uniqueAuthorsInBatch,
                config.analysisOutputPath,
            )

        # open output directory
        explore(config.analysisOutputPath)

    finally:
        # close repo to avoid resource leaks
        if "repo" in locals():
            del repo


class Progress(git.remote.RemoteProgress):
    def update(self, op_code, cur_count, max_count=None, message=""):
        print(self._cur_line, end="\r")


def commitDate(tag):
    return tag.commit.committed_date


# https://stackoverflow.com/a/50965628
def explore(path):
    # explorer would choke on forward slashes
    path = os.path.normpath(path)

    if os.path.isdir(path):
        subprocess.run([FILEBROWSER_PATH, path])
    elif os.path.isfile(path):
        subprocess.run([FILEBROWSER_PATH, "/select,", os.path.normpath(path)])


if __name__ == "__main__":
    main(sys.argv[1:])
