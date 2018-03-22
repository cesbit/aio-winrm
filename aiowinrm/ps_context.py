import uuid

from aiowinrm.errors import AIOWinRMException
from aiowinrm.psrp.defragmenter import MessageDefragmenter
from aiowinrm.psrp.fragmenter import Fragmenter
from aiowinrm.psrp.messages import \
    create_session_capability_message, init_runspace_pool_message, \
    create_pipeline_message
from aiowinrm.psrp.ps_pipeline_reader import PipelineReader
from aiowinrm.psrp.ps_response_reader import PsResponseReader
from aiowinrm.soap.protocol import \
    create_power_shell_payload, parse_create_shell_response, get_ps_response, \
    command_output, close_shell_payload, create_ps_pipeline, parse_create_command_response, \
    create_send_payload
from aiowinrm.winrm_connection import WinRmConnection


EXIT_CODE_CODE = "\r\nif (!$?) { if($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 } }"


class PowerShellContext(object):

    def __init__(self, connection_options):
        self._connection_options = connection_options

        self.session_id = uuid.uuid4()
        self.runspace_id = uuid.uuid4()
        self.shell_id = None

        self._max_blob_length = None
        self._win_rm_connection = None
        self._shell_timed_out = False

        self._ps_reader = PsResponseReader(self._on_max_blob_len)

    def _on_max_blob_len(self, max_blob_length):
        self._max_blob_length = max_blob_length

    @property
    def _creation_payload(self):
        compat_msg = create_session_capability_message(self.runspace_id)
        runspace_msg = init_runspace_pool_message(self.runspace_id)
        creation_payload = Fragmenter.messages_to_fragment_bytes(
            messages=[compat_msg, runspace_msg],
            max_blob_length=self._max_blob_length)
        return creation_payload

    async def __aenter__(self):
        try:
            payload = create_power_shell_payload(self.runspace_id, self.session_id, self._creation_payload)
            self._win_rm_connection = WinRmConnection(self._connection_options)
            response = await self._win_rm_connection.request(payload)
            self.shell_id = parse_create_shell_response(response)

            get_ps_response_payload = get_ps_response(self.shell_id, self.session_id)
            defragmenter = MessageDefragmenter()
            while not self._ps_reader.opened and not self._ps_reader.exited:
                # print('requesting')
                response = await self._win_rm_connection.request(get_ps_response_payload)
                stream_gen = self._ps_reader.read_wsmv_message(response)
                message_gen = self._ps_reader.read_streams(stream_gen, defragmenter)
                # consume messages
                for _ in message_gen:
                    pass
            return self
        except Exception as ex:
            await self.__aexit__(ex=ex)
            raise

    async def start_script(self, script):
        try:
            self._check_pipeline_state()
            script += EXIT_CODE_CODE
            command_id = uuid.uuid4()
            message = create_pipeline_message(self.runspace_id, command_id, script)
            # print(message)
            for fragment in Fragmenter.messages_to_fragments([message], self._max_blob_length):
                if fragment.start_fragment:
                    payload = create_ps_pipeline(self.shell_id,
                                                 self.session_id,
                                                 command_id,
                                                 fragment.get_bytes())
                    data = await self._win_rm_connection.request(payload)
                    command_id = parse_create_command_response(data)
                else:
                    payload = create_send_payload(self.shell_id,
                                                  self.session_id,
                                                  command_id,
                                                  fragment.get_bytes())
                    await self._win_rm_connection.request(payload)
            return PipelineReader(command_id)
        except Exception as ex:
            await self.__aexit__(ex=ex)
            raise

    def _check_pipeline_state(self):
        if not self._ps_reader.opened:
            raise AIOWinRMException('Runspace not yet opened')
        if self._ps_reader.exited:
            raise AIOWinRMException('Runspace already exited')

    async def read_pipeline(self, pipeline):
        assert isinstance(pipeline, PipelineReader)
        try:
            self._check_pipeline_state()
            payload = command_output(self.shell_id, pipeline.command_id, power_shell=True)
            response = await self._win_rm_connection.request(payload)
            pipeline.read_command_state(response)
            stream_gen = self._ps_reader.read_wsmv_message(response)
            message_gen = self._ps_reader.read_streams(stream_gen, pipeline.defragmenter)
            for message in message_gen:
                pipeline.on_message(message)
        except Exception as ex:
            await self.__aexit__(ex=ex)
            raise

    async def __aexit__(self, ex=None, *a, **kw):
        self._ps_reader = None
        if not self._win_rm_connection:
            return
        if self.shell_id is None and ex is None:
            await self._win_rm_connection.close()
            raise RuntimeError("__aexit__ called without __aenter__")

        if self.shell_id:
            payload = close_shell_payload(self.shell_id, power_shell=True)
            await self._win_rm_connection.request(payload)
        await self._win_rm_connection.close()