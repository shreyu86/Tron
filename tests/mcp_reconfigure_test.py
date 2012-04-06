"""Tests for reconfiguring mcp."""
import tempfile

import yaml

from testify import TestCase, run, setup, assert_equal, teardown, suite
from tron import mcp, event
from tron.config import config_parse
from tron.serialize import filehandler

class MCPReconfigureTest(TestCase):

    def config_1(self, wd):
        config = dict(
            working_dir=wd,
            ssh_options=dict(
                agent=True,
                identities=['tests/test_id_rsa'],
            ),
            nodes=[
                dict(name='node0', hostname='batch0'),
                dict(name='node1', hostname='batch1'),
            ],
            node_pools=[dict(name='nodePool', nodes=['node0', 'node1'])],
            jobs=[
                dict(
                    name='test_unchanged',
                    node='node0',
                    schedule='daily',
                    actions=[dict(name='action_unchanged',
                                  command='command_unchanged') ]
                ),
                dict(
                    name='test_remove',
                    node='node1',
                    schedule=dict(interval='20s'),
                    actions=[dict(name='action_remove',
                                  command='command_remove')],
                ),
                dict(
                    name='test_change',
                    node='nodePool',
                    schedule=dict(interval='20s'),
                    actions=[
                        dict(name='action_change',
                             command='command_change'),
                        dict(name='action_remove2',
                             command='command_remove2',
                             requires=['action_change']),
                    ],
                ),
                dict(
                    name='test_daily_change',
                    node='node0',
                    schedule='daily',
                            actions=[dict(name='action_daily_change',
                                          command='command')],
                ),
            ])
        return yaml.dump(config)

    def config_2(self, wd):
        config = dict(
            working_dir=wd,
            ssh_options=dict(
                agent=True,
                identities=['tests/test_id_rsa'],
            ),
            nodes=[
                dict(name='node0', hostname='batch0'),
                dict(name='node1', hostname='batch1'),
            ],
            node_pools=[dict(name='nodePool', nodes=['node0', 'node1'])],
            command_context={
                'a_variable': 'is_constant'
            },
            jobs=[
                dict(
                    name='test_unchanged',
                    node='node0',
                    schedule='daily',
                    actions=[dict(name='action_unchanged',
                                  command='command_unchanged') ]
                ),
                dict(
                    name='test_change',
                    node='nodePool',
                    schedule='daily',
                    actions=[
                        dict(name='action_change',
                             command='command_changed'),
                    ],
                ),
                dict(
                    name='test_daily_change',
                    node='node0',
                    schedule='daily',
                            actions=[dict(name='action_daily_change',
                                          command='command_changed')],
                ),
                dict(
                    name='test_new',
                    node='nodePool',
                    schedule=dict(interval='20s'),
                    actions=[dict(name='action_new',
                                  command='command_new')]
                ),
            ])
        return yaml.dump(config)

    @setup
    def setup_mcp(self):
        self.test_dir = tempfile.mkdtemp()
        self.my_mcp = mcp.MasterControlProgram(self.test_dir, 'config')
        config = self.config_1(self.test_dir)
        self.my_mcp.apply_config(config_parse.load_config(config))

    @teardown
    def teardown_mcp(self):
        event.EventManager.get_instance().clear()
        filehandler.OutputPath(self.test_dir).delete()

    def reconfigure(self):
        config = self.config_2(self.test_dir)
        self.my_mcp.apply_config(config_parse.load_config(config))

    @suite('integration')
    def test_job_list(self):
        assert_equal(len(self.my_mcp.jobs), 4)
        self.reconfigure()
        assert_equal(len(self.my_mcp.jobs), 4)

    @suite('integration')
    def test_job_unchanged(self):
        assert 'test_unchanged' in self.my_mcp.jobs
        job_sched = self.my_mcp.jobs['test_unchanged']
        orig_job = job_sched.job
        run0 = job_sched.get_runs_to_schedule().next()
        run0.start()
        run1 = job_sched.get_runs_to_schedule().next()

        assert_equal(job_sched.job.name, "test_unchanged")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)
        assert_equal(action_map['action_unchanged'].name, 'action_unchanged')
        assert_equal(str(job_sched.job.scheduler), "DAILY")

        self.reconfigure()
        assert job_sched is self.my_mcp.jobs['test_unchanged']
        assert job_sched.job is orig_job

        assert_equal(len(job_sched.job.runs.runs), 2)
        assert_equal(job_sched.job.runs.runs[1], run0)
        assert_equal(job_sched.job.runs.runs[0], run1)
        assert run1.is_scheduled
        assert_equal(job_sched.job.context['a_variable'], 'is_constant')

    @suite('integration')
    def test_job_removed(self):
        assert 'test_remove' in self.my_mcp.jobs
        job_sched = self.my_mcp.jobs['test_remove']
        run0 = job_sched.get_runs_to_schedule().next()
        run0.start()
        run1 = job_sched.get_runs_to_schedule().next()

        assert_equal(job_sched.job.name, "test_remove")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)
        assert_equal(action_map['action_remove'].name, 'action_remove')

        self.reconfigure()
        assert not 'test_remove' in self.my_mcp.jobs
        assert not job_sched.job.enabled
        assert not run1.is_scheduled

    @suite('integration')
    def test_job_changed(self):
        assert 'test_change' in self.my_mcp.jobs
        job_sched = self.my_mcp.jobs['test_change']
        run0 = job_sched.get_runs_to_schedule().next()
        run0.start()
        job_sched.get_runs_to_schedule().next()
        assert_equal(len(job_sched.job.runs.runs), 2)

        assert_equal(job_sched.job.name, "test_change")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 2)

        self.reconfigure()
        new_job_sched = self.my_mcp.jobs['test_change']
        assert new_job_sched is job_sched
        assert new_job_sched.job is job_sched.job

        assert_equal(new_job_sched.job.name, "test_change")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)

        assert_equal(len(new_job_sched.job.runs.runs), 3)
        assert new_job_sched.job.runs.runs[1].is_cancelled
        assert new_job_sched.job.runs.runs[0].is_scheduled
        assert_equal(job_sched.job.context['a_variable'], 'is_constant')

    @suite('integration')
    def test_job_new(self):
        assert not 'test_new' in self.my_mcp.jobs
        self.reconfigure()

        assert 'test_new' in self.my_mcp.jobs
        job_sched = self.my_mcp.jobs['test_new']

        assert_equal(job_sched.job.name, "test_new")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)
        assert_equal(action_map['action_new'].name, 'action_new')
        assert_equal(action_map['action_new'].command, 'command_new')
        assert_equal(len(job_sched.job.runs.runs), 1)
        assert job_sched.job.runs.runs[0].is_scheduled

    @suite('integration')
    def test_daily_reschedule(self):
        job4 = self.my_mcp.jobs['test_daily_change']

        self.my_mcp.job_scheduler.next_runs(job4)

        assert_equal(len(job4.runs), 1)
        run = job4.runs[0]
        assert run.is_scheduled

        self.reconfigure()

        assert run.job is None

        assert_equal(len(job4.runs), 1)
        next_run = job4.runs[0]
        assert next_run is not run
        assert next_run.is_scheduled
        assert_equal(run.run_time, next_run.run_time)

    # TODO: test that global context change works for a jobs context


if __name__ == '__main__':
    run()