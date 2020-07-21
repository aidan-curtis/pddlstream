#!/usr/bin/env python2.7

from __future__ import print_function

import argparse
import os
import time
import datetime
import sys

from collections import defaultdict
from pddlstream.algorithms.focused import solve_focused
from pddlstream.language.generator import from_test, universe_test
from pddlstream.algorithms.constraints import PlanConstraints
from pddlstream.language.stream import StreamInfo, DEBUG
from pddlstream.utils import read, get_file_path, elapsed_time, INF, ensure_dir, safe_rm_dir, str_from_object
from pddlstream.language.external import defer_unique
from pddlstream.language.constants import print_solution, PDDLProblem, And, dump_pddlstream, is_plan, Fact, OBJECT
from pddlstream.algorithms.search import solve_from_pddl
from examples.fault_tolerant.logistics.run import test_from_bernoulli_fn, CachedFn
from examples.fault_tolerant.risk_management.run import EXPERIMENTS_DIR, PARALLEL_DIR, SERIAL, create_generator, fact_from_fd
from examples.pybullet.utils.pybullet_tools.utils import SEPARATOR, is_darwin, clip, DATE_FORMAT, \
    read_json, write_json
from pddlstream.algorithms.downward import parse_sequential_domain, parse_problem, \
    task_from_domain_problem, get_conjunctive_parts, TEMP_DIR, set_cost_scale, make_predicate
#from pddlstream.language.write_pddl import get_problem_pddl

P_SUCCESS = 0.9

# TODO: parse problem.pddl directly

OBJECTS = """
data-0-3 data-0-5 data-1-2 data-1-4 data-2-1 - data
script1 script2 script3 script4 script5 script6 script7 script8 script9 script10 - script
server1 server2 server3 - server
number0 number1 number2 number3 number4 number5 number6 number7 number8 number9 number10 number11 number12 number13 number14 number15 number16 - numbers
"""

INIT = """
(SCRIPT-IO script1 data-0-3 data-0-5 data-1-4)
(SCRIPT-IO script2 data-0-5 data-0-3 data-1-2)
(SCRIPT-IO script3 data-1-4 data-0-5 data-2-1)
(SCRIPT-IO script4 data-0-3 data-0-5 data-1-4)
(SCRIPT-IO script5 data-1-2 data-0-5 data-2-1)
(SCRIPT-IO script6 data-1-2 data-0-3 data-2-1)
(SCRIPT-IO script7 data-0-5 data-0-3 data-1-2)
(SCRIPT-IO script8 data-1-4 data-1-2 data-2-1)
(SCRIPT-IO script9 data-0-3 data-0-5 data-1-4)
(SCRIPT-IO script10 data-1-2 data-1-4 data-2-1)
(CONNECTED server1 server2)
(CONNECTED server2 server1)
(CONNECTED server1 server3)
(CONNECTED server3 server1)
(DATA-SIZE data-0-3 number4)
(DATA-SIZE data-0-5 number5)
(DATA-SIZE data-1-2 number4)
(DATA-SIZE data-1-4 number1)
(DATA-SIZE data-2-1 number4)
(CAPACITY server1 number16)
(CAPACITY server2 number8)
(CAPACITY server3 number8)
(saved data-0-3 server3)
(saved data-0-5 server1)
(usage server1 number0)
(usage server2 number0)
(usage server3 number0)
"""
# Removed functions for now

CLASSICAL_PATH = '/Users/caelan/Programs/domains/classical-domains/classical'
# ls /Users/caelan/Programs/domains/classical-domains/classical/*-opt18

DATA_NETWORK_PATH = os.path.join(CLASSICAL_PATH, 'data-network-opt18')
TERMES_PATH = os.path.join(CLASSICAL_PATH, 'termes-opt18')

#TERMES_PATH = '/Users/caelan/Documents/IBM/termes-opt18-strips-untyped'

##################################################

def get_optimal_benchmarks():
    directory = CLASSICAL_PATH
    return {os.path.join(directory, f) for f in sorted(os.listdir(directory)) if f.endswith('-opt18')}

def get_benchmarks(directory):
    pddl_files = {os.path.join(directory, f) for f in sorted(os.listdir(directory)) if f.endswith('.pddl')}
    domain_files = {f for f in pddl_files if os.path.basename(f) == 'domain.pddl'}
    if len(domain_files) != 1:
        raise RuntimeError(directory, domain_files)
    [domain_file] = list(domain_files)
    problem_files = sorted(pddl_files - domain_files)
    return domain_file, problem_files

##################################################

def object_facts_from_str(s):
    objs, ty = s.strip().rsplit(' - ', 1)
    return [(ty, obj) for obj in objs.split(' ')]

def fact_from_str(s):
    return tuple(s.strip('( )').split(' '))

def int_from_str(s):
    return int(s.replace('number', ''))

##################################################

def get_problem():
    domain_pddl = read(get_file_path(__file__, 'domain.pddl'))
    constant_map = {}
    stream_pddl = read(get_file_path(__file__, 'stream.pddl'))

    # TODO: compare statistical success and the actual success
    bernoulli_fns = {
        #'test-open': fn_from_constant(P_SUCCESS),
    }

    # universe_test | empty_test
    stream_map = {
        'test-less_equal': from_test(lambda x, y: int_from_str(x) <= int_from_str(y)),
        'test-sum': from_test(lambda x, y, z: int_from_str(x) + int_from_str(y) == int_from_str(z)),
        'test-online': from_test(universe_test),
    }
    stream_map.update({name: from_test(CachedFn(test_from_bernoulli_fn(fn)))
                       for name, fn in bernoulli_fns.items()})

    init = [fact_from_str(s) for s in INIT.split('\n') if s]
    for line in OBJECTS.split('\n'):
        if line:
            init.extend(object_facts_from_str(line))

    goal_literals = [
        'saved data-2-1 server2',
    ]

    goal = And(*map(fact_from_str, goal_literals))

    return PDDLProblem(domain_pddl, constant_map, stream_pddl, stream_map, init, goal)

##################################################

def get_parse():
    import pddl
    from pddl.pddl_types import _get_type_predicate_name
    domain_path, problem_paths = get_benchmarks(DATA_NETWORK_PATH)
    problem_path = problem_paths[0]
    #domain_path = get_file_path(__file__, 'domain.pddl')
    #problem_path = get_file_path(__file__, 'problem.pddl')

    #safe_rm_dir(TEMP_DIR) # TODO: fix re-running bug
    domain_pddl = read(domain_path)
    domain = parse_sequential_domain(domain_pddl)

    for action in domain.actions:
        new_parameters = []
        new_preconditions = []
        for parameter in action.parameters:
            new_parameters.append(pddl.TypedObject(parameter.name, OBJECT))
            new_preconditions.append(parameter.get_atom())
        action.parameters = new_parameters # Not necessary
        action.precondition = pddl.Conjunction([action.precondition] + new_preconditions).simplified()

    # for ty in domain.types:
    #     #pddl._get_type_predicate_name
    #     name = _get_type_predicate_name(ty.name)
    #     predicate = make_predicate(name, '?o')
    #     domain.predicates.append(predicate)
    #     domain.predicate_dict[name] = predicate

    domain.types.clear()
    domain.type_dict.clear()
    object_type = pddl.Type(OBJECT, basetype_name=None)
    object_type.supertype_names = []
    domain.types.append(object_type)
    domain.type_dict[object_type.name] = object_type

    assert not domain.axioms
    domain_pddl = domain

    assert not domain.constants
    constant_map = {}

    problem_pddl = read(problem_path)
    problem = parse_problem(domain, problem_pddl)
    #task = task_from_domain_problem(domain, problem) # Uses Object

    stream_pddl = read(get_file_path(__file__, 'stream.pddl'))
    stream_pddl = None
    stream_map = DEBUG

    initial = problem.init + [obj.get_atom() for obj in problem.objects]
    init = list(map(fact_from_fd, initial))
    goal = And(*map(fact_from_fd, get_conjunctive_parts(problem.goal)))
    # TODO: throw error is not a conjunction

    return PDDLProblem(domain_pddl, constant_map, stream_pddl, stream_map, init, goal)

##################################################

def solve_pddlstream(n_trials=1):
    # TODO: make a simulator that randomizes these probabilities
    # TODO: include local correlation

    planner = 'forbid' # forbid | kstar
    diverse = {'selector': 'greedy', 'metric': 'p_success', 'k': 5}  # , 'max_time': 30

    stream_info = {
        'test-less_equal': StreamInfo(eager=True, p_success=0),
        'test-sum': StreamInfo(eager=True, p_success=0), # TODO: p_success=lambda x: 0.5
        'test-online': StreamInfo(p_success=P_SUCCESS, defer_fn=defer_unique),
    }
    #problem = get_problem()
    problem = get_parse()
    dump_pddlstream(problem)

    successes = 0.
    for _ in range(n_trials):
        print('\n'+'-'*5+'\n')
        #problem = get_problem(**kwargs)
        #solution = solve_incremental(problem, unit_costs=True, debug=True)
        solutions = solve_focused(problem, stream_info=stream_info, # planner='forbid'
                                  unit_costs=True, unit_efforts=False, debug=True,
                                  planner=planner, max_planner_time=10, diverse=diverse,
                                  initial_complexity=1, max_iterations=1, max_skeletons=None,
                                  replan_actions=['load'],
                                  )
        for solution in solutions:
            print_solution(solution)
            #plan, cost, certificate = solution
            #successes += is_plan(plan)
        successes += bool(solutions)
    print('Fraction {:.3f}'.format(successes / n_trials))

##################################################

# https://bitbucket.org/ipc2018-classical/workspace/projects/GEN

def solve_trial(inputs, planner='forbid', max_time=1*10):
    # TODO: randomize the seed
    pid = os.getpid()
    domain_path, problem_path = inputs['domain_path'], inputs['problem_path']
    print(SEPARATOR)
    print('Process {}: {}'.format(pid, inputs))

    stdout = sys.stdout
    current_wd = os.getcwd()
    trial_wd = os.path.join(current_wd, PARALLEL_DIR, '{}/'.format(pid))
    if not SERIAL:
        sys.stdout = open(os.devnull, 'w')
        safe_rm_dir(trial_wd)
        ensure_dir(trial_wd)
        os.chdir(trial_wd)

    domain_pddl, problem_pddl = read(domain_path), read(problem_path)
    start_time = time.time()
    solutions = solve_from_pddl(domain_pddl, problem_pddl, planner=planner,
                                max_planner_time=max_time, max_cost=INF, debug=True)
    outputs = dict(inputs)
    outputs.update({'planner': planner, 'max_time': max_time,
                    'runtime': elapsed_time(start_time), 'num_plans': len(solutions)})

    evaluations = []
    for i, (plan, cost) in enumerate(solutions):
        print('\nPlan {}/{}'.format(i + 1, len(solutions)), )
        solution = (plan, cost, evaluations)
        print_solution(solution)

    if not SERIAL:
        os.chdir(current_wd)
        #safe_rm_dir(trial_wd)
        sys.stdout.close()
        sys.stdout = stdout
    # git status -u --ignored

    return inputs, outputs

def solve_pddl():
    # No restriction to be untyped here
    set_cost_scale(1)
    #constraints = PlanConstraints(max_cost=INF) # kstar

    #from examples.blocksworld.run import read_pddl
    #domain_pddl, problem_pddl = read_pddl('domain.pddl'), read_pddl('problem.pddl') # Blocksworld

    directory_paths = get_optimal_benchmarks()
    #directory_paths = [TERMES_PATH] # create-block, destroy-block
    problems = []
    for directory_path in directory_paths:
        try:
            domain_path, problem_paths = get_benchmarks(directory_path)
        except RuntimeError:
            continue
        #problem_paths = problem_paths[:1] # 0, -1
        for problem_path in problem_paths:
            print(domain_path, problem_path)
            problems.append({'domain_path': domain_path, 'problem_path': problem_path})
    print(problems)
    generator = create_generator(solve_trial, problems)

    ensure_dir(EXPERIMENTS_DIR)
    date_name = datetime.datetime.now().strftime(DATE_FORMAT)
    #file_name = os.path.join(EXPERIMENTS_DIR, '{}.pk3'.format(date_name))
    file_name = os.path.join(EXPERIMENTS_DIR, '{}.json'.format(date_name))
    results = []
    for inputs, outputs in generator:
        results.append(outputs)
        if not SERIAL:
            #write_pickle(file_name, results)
            write_json(file_name, results)
            print('Wrote {}'.format(file_name))

##################################################

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--experiment', default=None)
    args = parser.parse_args()
    if args.experiment is None:
        solve_pddlstream()
        #solve_pddl()
    else:
        counter = defaultdict(int)
        results = read_json(args.experiment)
        for result in results:
            if result['num_plans'] >= 10:
                print(result['num_plans'], result['problem_path'])
                counter[result['domain_path']] += 1
        print(str_from_object(counter))
        # for key in sorted(counter):
        #     print(counter[key], key)

if __name__ == '__main__':
    main()

# TODO: extend PDDLStream to support typing directly

# https://github.com/AI-Planning/classical-domains/tree/master/classical/data-network-opt18
# TODO: load the initial state from a problem file
# Packet sizes
# https://github.com/tomsilver/pddlgym/blob/master/rendering/tsp.py
# https://networkx.github.io/
# https://pypi.org/project/graphviz/

# ./FastDownward/fast-downward.py --show-aliases
# ./FastDownward/fast-downward.py --build release64 --alias lama examples/fault_tolerant/data_network/domain.pddl examples/fault_tolerant/data_network/problem.pddl