from datetime import timedelta
from pathlib import Path
from typing import Optional, Collection, List, Dict, IO

from psij import Job, JobStatus, JobState, SubmitException
from psij.executors.batch.batch_scheduler_executor import BatchSchedulerExecutor, \
    BatchSchedulerExecutorConfig, check_status_exit_code
from psij.executors.batch.script_generator import TemplatedScriptGenerator


#_SQUEUE_COMMAND = 'squeue'
_PJSTAT_COMMAND = 'pjstat'


class PJsubExecutorConfig(BatchSchedulerExecutorConfig):
    """A configuration class for the PJsub executor."""

    pass


class PJsubJobExecutor(BatchSchedulerExecutor):
    """A :class:`~psij.JobExecutor` for the PJsub Workload Manager.

    The `Slurm Workload Manager <https://slurm.schedmd.com/overview.html>`_ is a
    widely used resource manager running on machines such as
    NERSC's Perlmutter, as well as a variety of LLNL machines.

    Uses the 'sbatch', 'squeue', and 'scancel' commands, respectively, to submit,
    monitor, and cancel jobs.

    Creates a batch script with #SBATCH directives when submitting a job.

    Renders all custom attributes set on a job's attributes with a `slurm.` prefix into
    corresponding Slurm directives with long-form parameters. For example,
    `job.spec.attributes.custom_attributes['slurm.qos'] = 'debug'` causes a directive
    `#SBATCH --qos=debug` to be placed in the submit script.
    """

    # see https://slurm.schedmd.com/squeue.html
    _STATE_MAP = {
        'ACC': JobState.QUEUED,
        'CCL': JobState.CANCELED,
        'ERR': JobState.FAILED,
        'EXT': JobState.COMPLETED,
        'HLD': JobState.QUEUED,
        'QUE': JobState.QUEUED,
        'RJT': JobState.FAILED,
        'RNA': JobState.ACTIVE,
        'RNE': JobState.ACTIVE,
        'RNO': JobState.CANCELED,
        'RNP': JobState.ACTIVE,
        'RSM': JobState.ACTIVE,
        'RUN': JobState.ACTIVE,
        'SPD': JobState.QUEUED,
        'SPP': JobState.QUEUED,
    }

    # see https://slurm.schedmd.com/squeue.html
    _REASONS_MAP = {
        '':'No error',
        'ANOTHER JOB STARTED': 'A job that was running beyond the minimum runnable time for the job has been terminated to run a subsequent job.',
        'DEADLINE SCHEDULE STARTED': 'A job that was running beyond the minimum job execution time was terminated due to the start of the deadline schedule.',
        'ELAPSE LIMIT EXCEEDED': 'The elapsed time limit has been exceeded.',
        'FILE IO ERROR': 'The current directory when the user’s job is submitted cannot be accessed.',
        'GATE CHECK': 'Canceled by the job manager exit function.',
        'IMPOSSIBLE SCHED': 'Scheduling failed.',
        'INSUFF CPU': 'There is a physical shortage of CPUs.',
        'INSUFF MEMORY': 'There is a physical memory shortage.',
        'INSUFF NODE': 'The number of nodes is physically insufficient.',
        'INSUFF CustomResourceName': 'The custom resource defined by the resource name CustomResourceName is insufficient.',
        'INTERNAL ERROR': 'Internal error.',
        'INVALID HOSTFILE': 'The host file is unmatched which specified with rank-map-hostfile parameter of pjsub command.',
        'LIMIT OVER MEMORY': 'The memory limit was exceeded during job execution.',
        'LOST COMM': 'All-to-all communication of parallel processes is not guaranteed.',
        'NO CURRENT DIR': 'The current directory or standard input / standard output / standard error output file when the user job was submitted could not be accessed.',
        'NOT EXIST CustomResourceName': 'A custom resource with the resource name CustomResourceName is not defined.',
        'RESUME FAIL': 'Resume failed.',
        'RSCGRP NOT EXIST': 'Resource group does not exist.',
        'RSCGRP STOP': 'The resource group has stopped.',
        'RSCUNIT NOT EXIST': 'Resource unit does not exist.',
        'RSCUNIT STOP': 'The resource unit has stopped.',
        'RUNLIMIT EXCEED': 'The maximum number of concurrent job executions has been exceeded.',
        'SUSPEND FAIL': 'Suspend failed.',
        'USELIMIT EXCEED': 'Waiting for execution due to simultaneous node limit or concurrent CPU core limit.',
        'USER NOT EXIST': 'The job execution user does not exist in the system.',
        'WAIT SCHED': 'The number of jobs subject to scheduling has been reached, so it has been excluded from scheduling.',
        # '': '',
    }

    def __init__(self, url: Optional[str] = None, config: Optional[PJsubExecutorConfig] = None):
        """
        Parameters
        ----------
        url
            Not used, but required by the spec for automatic initialization.
        config
            An optional configuration for this executor.
        """
        if not config:
            config = PJsubExecutorConfig()
        super().__init__(config=config)
        self.generator = TemplatedScriptGenerator(config, Path(__file__).parent / 'pjsub' / 'pjsub.mustache')

    def generate_submit_script(self, job: Job, context: Dict[str, object],
                               submit_file: IO[str]) -> None:
        """See :meth:`~.BatchSchedulerExecutor.generate_submit_script`."""
        self.generator.generate_submit_script(job, context, submit_file)

    def get_submit_command(self, job: Job, submit_file_path: Path) -> List[str]:
        """See :meth:`~.BatchSchedulerExecutor.get_submit_command`."""
        return ['pjsub', '--no-check-directory' , str(submit_file_path.absolute())]

    def get_cancel_command(self, native_id: str) -> List[str]:
        """See :meth:`~.BatchSchedulerExecutor.get_cancel_command`."""
        return ['pjdel', native_id]

    def process_cancel_command_output(self, exit_code: int, out: str) -> None:
        """See :meth:`~.BatchSchedulerExecutor.process_cancel_command_output`."""
        raise SubmitException('Failed job cancel job: %s' % out)

    def get_status_command(self, native_ids: Collection[str]) -> List[str]:
        """See :meth:`~.BatchSchedulerExecutor.get_status_command`."""
        # we're not really using job arrays, so this is equivalent to the job ID. However, if
        # we were to use arrays, this would return one ID for the entire array rather than
        # listing each element of the array independently
        #return [_SQUEUE_COMMAND, '-O', 'JobArrayID,StateCompact,Reason', '-t', 'all', '--me']
        return [_PJSTAT_COMMAND, '--choose', 'jid,st,ermsg', '-v', '&&', '(', _PJSTAT_COMMAND, '--history', '--choose', 'jid,st,ermsg', '-v', '|', 'tail -n +2', ')']

    def parse_status_output(self, exit_code: int, out: str) -> Dict[str, JobStatus]:
        """See :meth:`~.BatchSchedulerExecutor.parse_status_output`."""
        #check_status_exit_code(_SQUEUE_COMMAND, exit_code, out)
        check_status_exit_code(_PJSTAT_COMMAND, exit_code, out)
        r = {}
        lines = iter(out.split('\n')[:-1])
        # skip header
        lines.__next__()
        for line in lines:
            if not line:
                continue
            cols = line.split()
            assert len(cols) == 3
            native_id = cols[0]
            state = self._get_state(cols[1])
            msg = self._get_message(cols[2]) if state == JobState.FAILED else None
            r[native_id] = JobStatus(state, message=msg)

        return r

    def get_list_command(self) -> List[str]:
        """See :meth:`~.BatchSchedulerExecutor.get_list_command`."""
        #return ['squeue', '--me', '-o', '%i', '-h', '-r', '-t', 'all']
        return [_PJSTAT_COMMAND, '--choose', 'jid', '| tail -n +2' ]

    def _get_state(self, state: str) -> JobState:
        assert state in PJsubJobExecutor._STATE_MAP
        return PJsubJobExecutor._STATE_MAP[state]

    def _get_message(self, reason: str) -> str:
        assert reason in PJsubJobExecutor._REASONS_MAP
        return PJsubJobExecutor._REASONS_MAP[reason]

    def job_id_from_submit_output(self, out: str) -> str:
        """See :meth:`~.BatchSchedulerExecutor.job_id_from_submit_output`."""
        return out.strip().split()[-2]

    def _format_duration(self, d: timedelta) -> str:
        # https://slurm.schedmd.com/sbatch.html#OPT_time:
        #   Acceptable time formats include "minutes", "minutes:seconds", "hours:minutes:seconds",
        #   "days-hours", "days-hours:minutes" and "days-hours:minutes:seconds".
        days = ''
        if d.days > 0:
            days = str(d.days) + '-'
        return days + "%s:%s:%s" % (d.seconds // 3600, (d.seconds // 60) % 60, d.seconds % 60)

    def _clean_submit_script(self, job: Job) -> None:
        super()._clean_submit_script(job)
        self._delete_aux_file(job, '.nodefile')
