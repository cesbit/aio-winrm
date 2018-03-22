from aiowinrm.psrp.messagedata.message_data import MessageData
from aiowinrm.psrp.messagedata.runspacepool_state import \
    RunspacePoolStateEnum, RunspacePoolState
from aiowinrm.psrp.messagedata.session_capability import SessionCapability
from aiowinrm.soap.protocol import get_streams, parse_command_done


class PsResponseReader(object):
    """
    Takes in wsmv messages and turns them into std_out, std_err, exit_code
    Will also keep track of opened/closed stated
    """

    def __init__(self, on_max_blob_len):
        self._on_max_blob_len = on_max_blob_len
        self._opened = False
        self._closed = False

    def read_wsmv_message(self, message_node):
        print('WSMV message')
        soap_stream_gen = get_streams(message_node)
        return soap_stream_gen

    def read_streams(self, stream_gen, defragmenter):
        for soap_stream_type, messages in defragmenter.streams_to_messages(stream_gen):
            assert soap_stream_type == 'stdout'
            for decoded_message in messages:
                assert isinstance(decoded_message, MessageData)
                if isinstance(decoded_message, RunspacePoolState):
                    if decoded_message.runspace_state == RunspacePoolStateEnum.OPENED:
                        self._opened = True
                    elif decoded_message.runspace_state == RunspacePoolStateEnum.CLOSED:
                        self._closed = True
                elif isinstance(decoded_message, SessionCapability):
                    proto_version = tuple(map(int, decoded_message.protocol_version.split('.')))
                    max_blob_length = 512000 if proto_version > (2, 1) else 153600
                    self._on_max_blob_len(max_blob_length)

                yield decoded_message

    @property
    def opened(self):
        return self._opened

    @property
    def exited(self):
        return self._closed