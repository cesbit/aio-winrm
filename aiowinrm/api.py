from base64 import b64encode

from aiowinrm.command_context import CommandContext
from aiowinrm.ps_context import PowerShellContext
from aiowinrm.shell_context import ShellContext
from aiowinrm.utils import check_for_bom, _clean_error_msg


async def run_cmd(connection_options,
                  command,
                  args=(),
                  env=None,
                  cwd=None):
    """
    Run the given command on the given host asynchronously.
    """
    async with ShellContext(connection_options, env=env, cwd=cwd) as shell_context:
        async with CommandContext(shell_context, command, args) as command_context:
            return_code = None
            stdout_buffer, stderr_buffer = [], []
            is_done = False
            while not is_done:
                stdout, stderr, return_code, is_done = await command_context.output_request()
                stdout_buffer.append(stdout)
                stderr_buffer.append(stderr)
            return ''.join(stdout_buffer), ''.join(stderr_buffer), return_code


async def run_ps(connection_options,
                 script,
                 execution_policy=None):
    """
    run PowerShell script over cmd+powershell

    :param connection_options:
    :param script:
    :return:
    """
    check_for_bom(script)
    encoded_ps = b64encode(script.encode('utf_16_le')).decode('ascii')
    if execution_policy is None:
        command = f'powershell -encodedcommand {encoded_ps}'
    else:
        command = f'powershell -ExecutionPolicy {execution_policy} -encodedcommand {encoded_ps}'
    res = await run_cmd(connection_options,
                        command=command)
    stdout, stderr, return_code = res
    if stderr:
        # if there was an error message, clean it it up and make it human
        # readable
        stderr = _clean_error_msg(stderr)
    return stdout, stderr, return_code


async def run_psrp(connection_options,
                   script):
    """
    run PowerShell script over PSRP protocol

    :param connection_options:
    :param script:
    :return:
    """
    check_for_bom(script)
    async with PowerShellContext(connection_options) as pwr_shell_context:
        pipeline = await pwr_shell_context.start_script(script)
        while not pipeline.exited:
            await pwr_shell_context.read_pipeline(pipeline)
    std_out, std_err = pipeline.get_output()
    return std_out, std_err, pipeline.exit_code
