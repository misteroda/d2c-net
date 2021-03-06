# import sys
import os
# sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from experiment import Experiment
from agent.matching_policy import GreedyMatchingPolicy
from dqn.dqn_policy import DQNDispatchPolicy, DQNDispatchPolicyLearner
from dqn.demand_loader import DemandLoader
from dqn.settings import NUM_SUPPLY_DEMAND_HISTORY, FLAGS
from config.settings import TIMESTEP, DEFAULT_LOG_DIR, MAP_WIDTH, MAP_HEIGHT
from common.time_utils import get_local_datetime
from common import mesh


def setup_base_log_dir(base_log_dir):
    base_log_path = "./logs/{}".format(base_log_dir)
    if not os.path.exists(base_log_path):
        os.makedirs(base_log_path)
    for dirname in ["sim"]:
        p = os.path.join(base_log_path, dirname)
        if not os.path.exists(p):
            os.makedirs(p)
    if FLAGS.train:
        for dirname in ["networks", "summary", "memory"]:
            p = os.path.join(base_log_path, dirname)
            if not os.path.exists(p):
                os.makedirs(p)

    if os.path.exists(DEFAULT_LOG_DIR):
        os.unlink(DEFAULT_LOG_DIR)
    os.symlink(base_log_dir, DEFAULT_LOG_DIR)


def sample_initial_locations(t):
    locations = [mesh.convert_xy_to_lonlat(x, y)[::-1] for x in range(MAP_WIDTH) for y in range(MAP_HEIGHT)]
    p = DemandLoader.load_demand_profile(t)
    p = p.flatten() / p.sum()
    vehicle_locations = [locations[i] for i in np.random.choice(len(locations), size=FLAGS.vehicles, p=p)]
    return vehicle_locations


if __name__ == '__main__':
    setup_base_log_dir(FLAGS.tag)

    if FLAGS.train:
        print("Set training mode")
        dispatch_policy = DQNDispatchPolicyLearner()
        dispatch_policy.build_q_network(load_network=FLAGS.load_network)

        if FLAGS.load_memory:
            dispatch_policy.load_experience_memory(FLAGS.load_memory)

        if FLAGS.pretrain > 0:
            for i in range(FLAGS.pretrain):
                average_loss, average_q_max = dispatch_policy.train_network(FLAGS.batch_size)
                print("iterations : {}, average_loss : {:.3f}, average_q_max : {:.3f}".format(
                    i, average_loss, average_q_max), flush=True)
                dispatch_policy.q_network.write_summary(average_loss, average_q_max)

    else:
        dispatch_policy = DQNDispatchPolicy()
        if FLAGS.load_network:
            dispatch_policy.build_q_network(load_network=FLAGS.load_network)

    if FLAGS.days > 0:
        start_time = FLAGS.start_time + int(60 * 60 * 24 * FLAGS.start_offset)
        print("Start Datetime: {}".format(get_local_datetime(start_time)))
        end_time = start_time + int(60 * 60 * 24 * FLAGS.days)
        print("End Datetime  : {}".format(get_local_datetime(end_time)))

        matching_policy = GreedyMatchingPolicy()
        dqn_exp = Experiment(start_time, TIMESTEP, dispatch_policy, matching_policy)
        n_steps = int(3600 * 24 / TIMESTEP)
        buffer_steps = int(3600 / TIMESTEP)

        for _ in range(FLAGS.days):
            vehicle_locations = sample_initial_locations(dqn_exp.simulator.get_current_time() + 3600 * 3)
            dqn_exp.populate_vehicles(vehicle_locations)
            for i in range(n_steps):
                dqn_exp.step(verbose=FLAGS.verbose)

        vehicle_locations = sample_initial_locations(dqn_exp.simulator.get_current_time() + 3600 * 3)
        dqn_exp.populate_vehicles(vehicle_locations)
        for i in range(buffer_steps):
            dqn_exp.step(verbose=FLAGS.verbose)

        if FLAGS.train:
            print("Dumping experience memory as pickle...")
            dispatch_policy.dump_experience_memory()

