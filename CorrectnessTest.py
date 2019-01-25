from os import path, chdir, makedirs
from subprocess import Popen, PIPE
import subprocess
import time
import xml.etree.ElementTree as ET
import json
from argparse import ArgumentParser
import requests
import io
from zipfile import ZipFile

with open("config.json") as f:
    config = json.load(f)

proj_config_dir = path.abspath("proj-config")

env = config["environment"]

resharper_build = env["build directory"]
inspect_code_path = path.join(resharper_build, "inspectcode.x86.exe")

cli_test_dir = env["test directory"]
projects_dir = path.join(cli_test_dir, "projects")
caches_home = path.join(cli_test_dir, "caches-home")

def get_sources_from_git(project_input, target_dir):
    if not path.exists(path.join(target_dir, ".git")):
        subprocess.run(["git", "clone", project_input["repo"], target_dir], check=True)

    chdir(target_dir)
    subrepo = project_input.get("subrepo")
    if subrepo:
        subrepo_dir = subrepo["path"]
        if not path.exists(path.join(subrepo_dir, ".git")):
            subprocess.run(["git", "clone", subrepo["url"], subrepo_dir], check=True)
        chdir(subrepo_dir)
        subprocess.run(["git", "checkout", subrepo["commit"]], check=True, stdout=PIPE, stderr=PIPE)
        chdir(target_dir)

    subprocess.run(["git", "submodule", "update", "--init"], check=True, stdout=PIPE, stderr=PIPE)
    subprocess.run(["git", "checkout", project_input["commit"]], check=True, stdout=PIPE, stderr=PIPE)
    root_dir = project_input.get("root")
    if root_dir:
        return path.join(target_dir, root_dir)
    else:
        return target_dir

def get_sources_from_zip(project_input, target_dir):
    root_dir = path.join(target_dir, project_input["root"])
    if not path.exists(root_dir):
        response = requests.get(project_input["url"])
        with ZipFile(io.BytesIO(response.content)) as zipfile:
            zipfile.extractall(path=target_dir)
    return root_dir

def get_sources(project_input, target_dir):
    kind = project_input.get("kind")
    if not kind:
        return get_sources_from_git(project_input, target_dir)
    elif kind == "zip":
        return get_sources_from_zip(project_input, target_dir)
    else:
        raise ValueError("Unknown source kind: {0}".format(kind))

def invoke_cmake(build_dir, cmake_options):
    makedirs(build_dir, exist_ok=True)
    chdir(build_dir)
    cmd_line_args = ["cmake", "..", "-G", env["VS CMake Generator"]]
    if cmake_options:
        cmd_line_args.extend(cmake_options)
    subprocess.run(cmd_line_args, check=True, stdout=PIPE)
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
        if isinstance(project_to_check, list):
            for p in project_to_check:
                args.append("--project=" + p)
        else:
            assert(isinstance(project_to_check, str))
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


def add_entry(node, key, value):
    entry = ET.SubElement(node, "s:Boolean")
    entry.text = str(value)
    entry.set("x:Key", key)

def generate_settings(files_to_skip):
    root = ET.Element("wpf:ResourceDictionary")
    root.set("xml:space", "preserve")
    root.set("xmlns:x", "http://schemas.microsoft.com/winfx/2006/xaml")
    root.set("xmlns:s", "clr-namespace:System;assembly=mscorlib")
    root.set("xmlns:ss", "urn:shemas-jetbrains-com:settings-storage-xaml")
    root.set("xmlns:wpf", "http://schemas.microsoft.com/winfx/2006/xaml/presentation")

    add_entry(root, "/Default/CodeInspection/CppClangTidy/EnableClangTidySupport/@EntryValue", False)

    if files_to_skip:
        for f in files_to_skip:
            add_entry(root, "/Default/Environment/ExcludedFiles/FileMasksToSkip/={0}/@EntryIndexedValue".format(f), True)

    return ET.ElementTree(root)

def process_project(project_name, project):
    if isinstance(project, str):
        with open(path.join(proj_config_dir, project)) as pf:
            project = json.load(pf)

    target_dir = path.join(projects_dir, project_name)
    project_dir = get_sources(project["sources"], target_dir)
    #print("project directory: " + project_dir)
    custom_build_tool = project.get("custom build tool")
    if custom_build_tool:
        script = custom_build_tool.get("script")
        if script:
            chdir(project_dir)
            subprocess.run(script, check=True, stdout=PIPE)
        sln_file = path.join(project_dir, custom_build_tool["path to .sln"])
        assert(path.exists(sln_file))
    else:
        build_dir = path.join(project_dir, project.get("build dir", "build"))
        sln_file = invoke_cmake(build_dir, project.get("cmake options"))
        build_step = project.get("build step")
        if build_step:
            chdir(build_dir)
            subprocess.run(build_step.split(), check=True, stdout=PIPE)

    #print(".sln file: " + sln_file)
    generate_settings(project.get("to skip")).write(sln_file + ".DotSettings")

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
