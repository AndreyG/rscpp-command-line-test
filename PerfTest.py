import common

from os import path, chdir, makedirs
from subprocess import Popen, PIPE
import subprocess
import json
import time
import sys
import platform
import uuid
import shutil

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


def run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props, indexing):
    args, report_file = common.inspect_code_run_arguments(project_dir, sln_file, project_to_check, msbuild_props)
    args.insert(0, common.inspect_code_path)
    if indexing:
        args.append('--exclude="**"')
    #print(subprocess.list2cmdline(args))
    assert(invoke(args))
    result = []

    for attempt in range(10):
        print("attempt {0}".format(attempt))
        if indexing:
            shutil.rmtree(common.caches_home)
        start = time.time()
        assert(invoke(args))
        end = time.time()
        print("Elapsed time: " + common.duration(start, end))
        result.append(end - start)
    
    return result


def measure_project(project_name, project, indexing):
    project_dir, sln_file = common.prepare_project(project_name, project)

    project_to_check = project.get("project to check")
    msbuild_props = project.get("msbuild properties")
    return run_inspect_code(project_dir, sln_file, project_to_check, msbuild_props, indexing)


def get_process_version(cmd_args):
    process = Popen(cmd_args, stdout=PIPE, text=True)
    out, err = process.communicate()
    exit_code = process.wait()
    assert(exit_code == 0)
    assert(not err)
    return out.splitlines()
    
def get_inspect_code_version():
    output = get_process_version([common.inspect_code_path, "-v"])
    prefix = "Version: "
    for line in output:
        if line.startswith(prefix):
            return line[len(prefix):]


def get_environment():
    result = {}
    result["inspect code version"] = get_inspect_code_version()
    result["computer name"] = platform.node()
    return result


common.argparser.add_argument("--human-readable", dest="human_readable", action='store_true')
common.argparser.add_argument("--out-dir", dest="out_dir")
common.argparser.add_argument("--indexing", dest="indexing", action='store_true')
common.argparser.set_defaults(human_readable=False)
common.argparser.set_defaults(indexing=False)
args = common.argparser.parse_args()


def is_suitable_for_perf_test(project):
    return args.human_readable or not ("required dependencies" in project)


def process_project(project_name, project):
    result = measure_project(project_name, project, args.indexing)
    if args.human_readable:
        print(result)
    else:
        to_store = {}
        to_store["inspect-code results"] = result
        to_store["project"] = project_name
        to_store["environment"] = get_environment()
        project_sources = project["sources"]
        project_sources.pop("root", None)
        project_sources.pop("kind", None)
        to_store["project sources"] = project_sources
        output_dir = args.out_dir
        if not path.isabs(output_dir):
            output_dir = path.join(common.cli_test_dir, output_dir)
        output_dir = path.join(output_dir, project_name)
        makedirs(output_dir, exist_ok=True)
        output_path = path.join(output_dir, str(uuid.uuid4()) + ".json")
        print(output_path)
        with open(output_path, "w") as output:
            json.dump(to_store, output, indent=4)


project_name = args.project
if project_name:
    project = common.projects[project_name]
    project = common.read_conf_if_needed(project)
    if not is_suitable_for_perf_test(project):
        sys.exit("We are not ready yet to compare time perfomance results for projects with external dependecies")
    process_project(project_name, project)
else:
    items = list(common.projects.items())
    #items.reverse()
    start_time = time.time()

    for project_name, project in items:
        project = common.read_conf_if_needed(project)
        if not is_suitable_for_perf_test(project):
            continue
        print("processing project {0}...".format(project_name), flush=True)
        process_project(project_name, project)
        print('-------------------------------------------------------', flush=True)

    print("Total time: " + common.duration(start_time, time.time()))
    
