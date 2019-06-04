from argparse import ArgumentParser
from subprocess import Popen, PIPE
from os import path
import xml.etree.ElementTree as ET
import json
import time

import common


def print_errors(title, errors):
    if errors:
        print(title + " errors:")
        for f, l, m in errors:
            print(json.dumps({"file" : f, "line" : l, "message" : m}))
                

def check_report(report_file, known_errors):
    issue_nodes = ET.parse(report_file).getroot().findall("Issues")[0]
    if len(issue_nodes) == 0:
        print("No compilation errors found")
        if known_errors:
            print("But {0} errors were expected".format(len(known_errors)))
    else:
        errors = set([(issue.get("File"), issue.get("Line"), issue.get("Message")) for issue in issue_nodes.iter("Issue")])
        if known_errors:
            expected_errors = set([(issue["file"], issue["line"], issue["message"]) for issue in known_errors])
            unexpected_errors = errors.difference(expected_errors)
            missing_errors = expected_errors.difference(errors)
            print_errors("Unexpected", unexpected_errors)
            print_errors("Missing", missing_errors)
            if not unexpected_errors and not missing_errors:
                assert(len(expected_errors) == len(errors))
                print("{0} errors found as expected".format(len(errors)))
        else:
            print_errors("Unexpected", errors)


def duration(start, end):
    minutes, seconds = divmod(end - start, 60)
    return "{:02}:{:02}".format(int(minutes), int(seconds))


def run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props):
    args, report_file = common.inspect_code_run_arguments(project_dir, sln_file, project_to_check, msbuild_props)
    #print(subprocess.list2cmdline(args))
    process = Popen(args, stdout=PIPE, text=True)
    start = time.time()
    (out, err) = process.communicate()
    exit_code = process.wait()
    end = time.time()
    if exit_code != 0:
        print("Error: exit code = " + str(exit_code))
    if err:
        print("Error:")
        print(err)
    print("Elapsed time: " + duration(start, end))
    return report_file


proj_config_dir = path.abspath("proj-config")

def process_project(project_name, project):
    if isinstance(project, str):
        with open(path.join(proj_config_dir, project)) as pf:
            project = json.load(pf)

    project_dir, sln_file = common.prepare_project(project_name, project)

    project_to_check = project.get("project to check")
    msbuild_props = project.get("msbuild properties")
    report_file = run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props)
    check_report(report_file, project.get("known errors"))


with open("projects.json") as f:
    projects = json.load(f)

argparser = ArgumentParser()
argparser.add_argument("-p", "--project", dest="project")
args = argparser.parse_args()

if args.project:
    process_project(args.project, projects[args.project])
else:
    start_time = time.time()
    for project_name, project in projects.items():
        print("processing project {0}...".format(project_name))
        process_project(project_name, project)
        print('-------------------------------------------------------')
    print("Total time: " + duration(start_time, time.time()))
