import common

from subprocess import Popen, PIPE
import subprocess
import json
import time


def invoke(args):
    process = Popen(args, stdout=PIPE, text=True)
    out, err = process.communicate()
    exit_code = process.wait()
    end = time.time()
    if exit_code != 0:
        print("Error: exit code = " + str(exit_code))
        return False
    if err:
        print("Error:")
        print(err)
        return False
    return True


def run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props):
    args, report_file = common.inspect_code_run_arguments(project_dir, sln_file, project_to_check, msbuild_props)
    args.insert(0, common.inspect_code_path)
    #print(subprocess.list2cmdline(args))
    assert(invoke(args))
    result = []

    for attempt in range(10):
        print("attempt {0}".format(attempt))
        start = time.time()
        assert(invoke(args))
        end = time.time()
        print("Elapsed time: " + common.duration(start, end))
        result.append(end - start)
    
    print(result)


def process_project(project_name, project):
    project = common.read_conf_if_needed(project)

    project_dir, sln_file = common.prepare_project(project_name, project)

    project_to_check = project.get("project to check")
    msbuild_props = project.get("msbuild properties")
    run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props)


project = common.args.project
assert(project)
process_project(project, common.projects[project])
