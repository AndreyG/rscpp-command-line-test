from os import path, chdir, makedirs
from subprocess import Popen, PIPE
import subprocess
import xml.etree.ElementTree as ET
import json
import requests
import io
from zipfile import ZipFile

with open("environment.json") as f:
    env = json.load(f)

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

    custom_update_source_script = project_input.get("custom update source script")
    if custom_update_source_script:
        subprocess.run(custom_update_source_script, check=True, stdout=PIPE, stderr=PIPE)

    subprocess.run(["git", "checkout", project_input["commit"]], check=True, stdout=PIPE, stderr=PIPE)
    subprocess.run(["git", "submodule", "update", "--init"], check=True, stdout=PIPE, stderr=PIPE)
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

def invoke_cmake(build_dir, cmake_options, required_dependencies):
    makedirs(build_dir, exist_ok=True)
    chdir(build_dir)
    cmd_line_args = ["cmake", "..", "-G", env["VS CMake Generator"]]
    if required_dependencies:
        vcpkg = env.get("vcpkg")
        if vcpkg:
            cmd_line_args.append("-DCMAKE_TOOLCHAIN_FILE={0}/scripts/buildsystems/vcpkg.cmake".format(vcpkg))
        else:
            raise Exception("project has required dependencies {0}, but environment doesn't containt path to vcpkg".format(required_dependencies))
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
    

def inspect_code_run_arguments(project_dir, sln_file, project_to_check, msbuild_props):
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
    if msbuild_props:
        props = ["{0}={1}".format(key, value) for key, value in msbuild_props.items()]
        args.append("--properties:" + ";".join(props))

    args.append(sln_file)
    return args, report_file


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


def prepare_project(project_name, project):
    target_dir = path.join(projects_dir, project_name)
    project_dir = get_sources(project["sources"], target_dir)
    custom_build_tool = project.get("custom build tool")
    if custom_build_tool:
        prepare_sln_script = custom_build_tool.get("script")
        if prepare_sln_script:
            chdir(project_dir)
            subprocess.run(prepare_sln_script, check=True, stdout=PIPE)
        build_step = custom_build_tool.get("build step")
        if build_step:
            for step in build_step:
                subprocess.run(step.split(), check=True, stdout=PIPE)
        sln_file = path.join(project_dir, custom_build_tool["path to .sln"])
        assert(path.exists(sln_file))
    else:
        build_dir = path.join(project_dir, project.get("build dir", "build"))
        sln_file = invoke_cmake(build_dir, project.get("cmake options"), project.get("required dependencies"))
        build_step = project.get("build step")
        if build_step:
            chdir(build_dir)
            subprocess.run(build_step.split(), check=True, stdout=PIPE)

    generate_settings(project.get("to skip")).write(sln_file + ".DotSettings")
    return project_dir, sln_file