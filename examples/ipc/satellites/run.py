#!/usr/bin/env python

from __future__ import print_function

from pddlstream.pddlstream.algorithms.search import solve_from_pddl
from pddlstream.pddlstream.language.constants import read_pddl_pair
from pddlstream.examples.ipc.rovers.run import dump_plan

def main():
    domain_pddl, problem_pddl = read_pddl_pair(__file__)
    plan, cost = solve_from_pddl(domain_pddl, problem_pddl)
    dump_plan(plan, cost)

if __name__ == '__main__':
    main()
