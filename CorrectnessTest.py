from os import path, chdir, makedirs
from subprocess import Popen, PIPE
import subprocess
import time
import xml.etree.ElementTree as ET
import json
from argparse import ArgumentParser

with open("config.json") as f:
    config = json.load(f)

env = config["environment"]

resharper_build = env["build directory"]
inspect_code_path = path.join(resharper_build, "inspectcode.x86.exe")

cli_test_dir = env["test directory"]
projects_dir = path.join(cli_test_dir, "projects")
caches_home = path.join(cli_test_dir, "caches-home")

def get_sources(project_input, target_dir):
    if not path.exists(path.join(target_dir, ".git")):
        subprocess.run(["git", "clone", project_input["repo"], target_dir], check=True)
    chdir(target_dir)
    subprocess.run(["git", "submodule", "update", "--init"], check=True, stdout=PIPE, stderr=PIPE)
    subprocess.run(["git", "checkout", project_input["commit"]], check=True, stdout=PIPE, stderr=PIPE)
    return target_dir

def invoke_cmake(project_dir):
    build_dir = path.join(project_dir, "build")
    makedirs(build_dir, exist_ok=True)
    chdir(build_dir)
    subprocess.run(["cmake", "..", "-G", env["VS CMake Generator"]], check=True, stdout=PIPE)
    with open(path.join(build_dir, "CMakeCache.txt")) as cmake_cache:
        for line in cmake_cache.readlines():
            if line.startswith("CMAKE_PROJECT_NAME"):
                project_name = line[line.find('=') + 1:].rstrip()
                sln_file = path.join(build_dir, project_name + ".sln")
                if not path.exists(sln_file):
                    raise Exception("solution file {0} does not exist".format(sln_file))
                return sln_file

def duration(start, end):
    minutes, seconds = divmod(end - start, 60)
    return "{:02}:{:02}".format(int(minutes), int(seconds))
    

def run_inspect_code(project_dir, sln_file, project_to_check):
    report_file = path.join(project_dir, "resharper-report.xml")
    args = [inspect_code_path, "-s=ERROR", "-f=Xml"]
    args.append("-o=" + report_file)
    args.append("--caches-home=" + caches_home)
    if project_to_check:
        args.append("--project=" + project_to_check)
    args.append(sln_file)
    process = Popen(args, stdout=PIPE, text=True)
    #print(subprocess.list2cmdline(args))
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

def process_project(project_name, project):
    target_dir = path.join(projects_dir, project_name)
    project_dir = get_sources(project["sources"], target_dir)
    #print("project directory: " + project_dir)
    sln_file = invoke_cmake(project_dir)
    #print(".sln file: " + sln_file)

    report_file = run_inspect_code(project_dir, sln_file, project.get("project to check"))
    check_report(report_file, project.get("known errors"))


argparser = ArgumentParser()
argparser.add_argument("-p", "--project", dest="project")
args = argparser.parse_args()

if args.project:
    process_project(args.project, config["projects"][args.project])
else:
    start_time = time.time()
    for project_name, project in config["projects"].items():
        print("processing project {0}...".format(project_name))
        process_project(project_name, project)
        print('-------------------------------------------------------')
    print("Total time: " + duration(start_time, time.time()))
