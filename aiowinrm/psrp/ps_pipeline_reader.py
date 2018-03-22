from aiowinrm.psrp.defragmenter import MessageDefragmenter
from aiowinrm.psrp.ps_output_decoder import StreamTypeEnum, PsOutputDecoder
from aiowinrm.soap.protocol import parse_command_done


class PipelineReader(object):

    def __init__(self, command_id):
        self.command_id = command_id
        self.std_out = []
        self.std_err = []
        self.exit_code = None
        self.defragmenter = MessageDefragmenter()
        self._closed = False

    def read_command_state(self, message_node):
        command_done, exit_code = parse_command_done(message_node)
        if command_done:
            self._closed = True
            self.exit_code = exit_code

    def on_message(self, message):
        stream = PsOutputDecoder.get_stream(message)
        if stream:
            if stream.stream_type == StreamTypeEnum.STD_OUT:
                self.std_out.append(stream.text)
            elif stream.stream_type == StreamTypeEnum.STD_ERR:
                self.std_err.append(stream.text)

    @property
    def exited(self):
        if self.exit_code is not None:
            return True

    def get_output(self):
        return '\r\n'.join(self.std_out), '\r\n'.join(self.std_err)
