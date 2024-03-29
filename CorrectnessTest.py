from subprocess import Popen, PIPE
import subprocess
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
            return "no compilation errors found, but {0} errors were expected".format(len(known_errors))
        else:
            return None
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
                return None
            else:
                return "expected and actual set of errors differ"
        else:
            print_errors("Unexpected", errors)
            return "unexpected {0} errors found".format(len(errors))


def run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props):
    args, report_file = common.inspect_code_run_arguments(project_dir, sln_file, project_to_check, msbuild_props)
    args.insert(0, common.inspect_code_path)
    print(subprocess.list2cmdline(args))
    process = Popen(args, stdout=PIPE, text=True)
    start = time.time()
    out, err = process.communicate()
    exit_code = process.wait()
    end = time.time()
    if exit_code != 0:
        print("Error: exit code = " + str(exit_code))
    if err:
        print("Error:")
        print(err)
    print("Elapsed time: " + common.duration(start, end))
    return report_file, out


def check_project(project, project_dir, sln_file):
    project_to_check = project.get("project to check")
    msbuild_props = project.get("msbuild properties")
    report_file, output = run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props)
    expected_files_count = project.get("inspected files count")
    actual_files_count = common.inspected_files_count(output)
    if expected_files_count:
        if expected_files_count != actual_files_count:
            print("expected count of inspected files is {0}, but actual is {1}".format(expected_files_count, actual_files_count))
    else:
        print("count of inspected files is ", actual_files_count)
    return check_report(report_file, project.get("known errors"))


def process_project_with_cmake_generator(project, project_name, cmake_generator):
    project_dir, sln_file = common.prepare_project(project_name, project, cmake_generator)
    result = check_project(project, project_dir, sln_file)
    if result:
        name, _ = cmake_generator
        return "(" + name + ") " + result


def process_project(project_name, project):
    project = common.read_conf_if_needed(project)

    if "custom build tool" in project:
        project_dir, sln_file = common.prepare_project(project_name, project, None)
        return check_project(project, project_dir, sln_file)

    supported_generators = common.env["VS CMake Generators"]
    project_generators = project.get("cmake generators")

    if project_generators:
        for generator in project_generators:
            result = process_project_with_cmake_generator(project, project_name, (generator, supported_generators[generator]))
            if result:
                return result
    else:
        for cmake_generator in supported_generators.items():
            result = process_project_with_cmake_generator(project, project_name, cmake_generator)
            if result:
                return result

args = common.argparser.parse_args()
if args.project:
    process_project(args.project, common.projects[args.project])
else:
    summary = []
    start_time = time.time()

    for project_name, project in common.projects.items():
        print("processing project {0}...".format(project_name), flush=True)
        result = process_project(project_name, project)
        if result:
            summary.append(project_name + ": " + result)
        print('-------------------------------------------------------', flush=True)

    print("Total time: " + common.duration(start_time, time.time()))
    if len(summary) == 0:
        print("Summary: OK")
    else:
        print("Summary: Fail")
        for s in summary:
            print("    " + s)
