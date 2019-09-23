
import pygame as pg
import rtmidi
from itertools import izip
from rtmidi.midiconstants import NOTE_ON, NOTE_OFF


SYNTAX = {
    "block": ">",
    "state_close": "*",
    "runtime_cmd_close": ";",
    "cmd_string": "&",
    "assign": ":",
    "matrix": "x",
    "midi_param_sep": "+",
    "midi_desig": "|",
    "comment": "-"
}

KEYWORDS = {
    "red": "R",
    "green": "G",
    "blue": "B",
    "tempo": "BPM",
    "state": "S",
    "window": "W",
    "midi": "MD",
    "pitch": "P",
    "velocity": "V"
}

OUT_PORT_NAMES = {
    "pd": "Pure Data",
    "fluid": "FLUID Synth"
}

# Separates boxes
FRAME_WIDTH = 1

# Color
BLACK = 0, 0, 0

def parse_score(score):
    """Returns blocks"""
    with open(score, "r") as f:
        blocks = f.read().split(SYNTAX["block"])
        f.close()
        if f.closed:
            print "Score closed."
            return blocks
        else:
            raise OSError("Score not closed properly!")

def tokenize_block(block):
    """Returns single states"""
    return [s.strip() for s in block.split(SYNTAX["state_close"])]

# If length is > 1 there are preprocessor commands
def tokenize_state(state):
    """Returns commands; either [play_cmnds] or [preproc, play]cmds"""
    return [s.strip() for s in state.split(SYNTAX["runtime_cmd_close"])]

def tokenize_preproc(cmd):
    """Return single preproc cmds"""
    return cmd.split(SYNTAX["cmd_string"])

def break_lines(state):
    return state.split("\n")
    
def parse_cmd(cmd):
    """SYNTAX:value"""
    c, v = cmd.split(SYNTAX["assign"])
    if c in (KEYWORDS["state"], KEYWORDS["window"]):
        return c, [int(x) for x in v.split(SYNTAX["matrix"])]
    elif c in [KEYWORDS[k] for k in ("red", "green", "blue", "tempo")]:
        return c, int(v)
    else:
        raise RuntimeError("Invalid command {}".format(c))

def bpm_to_ms(bpm): return 60000 / bpm

def tokenize_midi_param(params):
    return params.split(SYNTAX["midi_param_sep"])

def parse_row_for_midi(row):
    if SYNTAX["midi_desig"] in row:
        return row.split(SYNTAX["midi_desig"])
    else:                       # No midi cmd written after light cmds
        return row, ""

def parse_izip_midi(midi_cmd):
    """Parse a midi_cmd and zip its params into a single midi msg.
    The order of params: P, V,
    """
    param_lists = [tokenize_midi_param(c) for c in tokenize_preproc(midi_cmd)]
    C = []                      # Converted
    for param_list in param_lists:
        try:
            C.append([float(x) for x in param_list])
        except ValueError:
            pass
    return izip(*C)


class MidiOutWrapper:
    def __init__(self, midi):
        self._midi = midi

    def channel_message(self, command, note, velocity, ch):
        """Send a MIDI channel mode message."""
        command = (command & 0xf0) | (ch - 1 & 0xf)
        msg = [command] + [value & 0x7f for value in (note, velocity)]
        self._midi.send_message(msg)

    def note_off(self, note, velocity=0, ch=1):
        """Send a 'Note Off' message."""
        self.channel_message(NOTE_OFF, note, velocity, ch=ch)

    def note_on(self, note, velocity=127, ch=1):
        """Send a 'Note On' message."""
        self.channel_message(NOTE_ON, note, velocity, ch=ch)

    # def program_change(self, program, ch=1):
    #     """Send a 'Program Change' message."""
    #     self.channel_message(PROGRAM_CHANGE, program, ch=ch)


class ScoreParser:
    def __init__(self, score):
        self.avec_midi = False
        self.blocks = parse_score(score)
        self.count_blocks = len(self.blocks[1:])
        # first block is always parsed in compiletime
        self.compiletime = self.compiletime_cmds()
        # rest are runtimes
        self.runtimes = self.runtime_cmds()
    
    def compiletime_cmds(self):
        cmds = dict()
        for cmd in tokenize_preproc(self.blocks[0].strip()):
            if cmd == KEYWORDS["midi"]:
                self.avec_midi = True
                # cmds[cmd] = True
            else:
                c, v = parse_cmd(cmd)
            cmds[c] = v
        return cmds

    def runtime_cmds(self):
        rt_cmds = []
        for i, block in enumerate(self.blocks[1:]):
            rt_cmds.insert(i, [])
            state_tokens = tokenize_block(block)
            for state_token in state_tokens:
                state = []
                cmd_tokens = tokenize_state(state_token)
                for cmd_token in cmd_tokens:
                    if cmd_token.startswith(("0", "1")):
                        lines = break_lines(cmd_token)
                        if self.avec_midi:  # There must be midi cmds
                            for line in lines:
                                state.append(parse_row_for_midi(line))
                        else:
                            lines = break_lines(cmd_token)
                            for line in lines:
                                state.append(line)
                    else:
                        for cmd in tokenize_preproc(cmd_token):
                            state.append(parse_cmd(cmd))
                rt_cmds[i].append(state)
        return rt_cmds

class Qust:
    add_to_userevent = 1
    def __init__(self,
                 win,
                 compiletime, runtimes,
                 loop, midiout):
        self.id_ = Qust.add_to_userevent
        self.win = win
        self.col, self.row = compiletime[KEYWORDS["state"]]
        # self.row, self.col = compiletime[KEYWORDS["state"]]
        # Alles muss in ScoreParser!
        # self.w = (compiletime[KEYWORDS["window"]][0] - 2 * self.col * FRAME_WIDTH) / self.col
        # self.h = (compiletime[KEYWORDS["window"]][1] - 2 * self.row * FRAME_WIDTH) / self.row
        self.w = compiletime[KEYWORDS["window"]][0] / self.col
        self.h = compiletime[KEYWORDS["window"]][1] / self.row
        #self.runtimes = iter(runtimes)
        # Search for rgbs in the first state
        # and replace unbound colors with 0s
        init_runtimes = filter(lambda elem: elem[0].startswith(("R", "G", "B")),
                             runtimes[0])
        unbound_rgbs = set(("R", "G", "B")).difference([x[0] for x in init_runtimes])
        for rgb in unbound_rgbs:
            runtimes[0].append((rgb, 0))
        if loop:
	    self.runtimes = iter(runtimes * loop)
        else:
            self.runtimes = iter(runtimes)
        self.timer_id = pg.USEREVENT + Qust.add_to_userevent
        Qust.add_to_userevent += 1
        self.timer_ms = pg.TIMER_RESOLUTION
        pg.time.set_timer(self.timer_id, self.timer_ms)
        self.rgb = [0, 0, 0]
        self.with_midi = False
        if midiout:
            self.midi_record = {k: None for k in range(self.row * self.col)}
            self.with_midi = True
            self.midiout = rtmidi.MidiOut(
                rtapi=rtmidi.API_UNIX_JACK,
                name="Qust")
            self.midiout = MidiOutWrapper(self.midiout)
            # Open the port
            for i, port in enumerate(self.midiout._midi.get_ports()):
                if OUT_PORT_NAMES[midiout] in port:
                    self.midiout._midi.open_port(i)
                    break
        self.qust = self.gen_qust()

    def close_midi_port(self):
        self.midiout._midi.close_port()
        print "Midi port {} closed? {}".format(self.midiout._midi,
                                               not self.midiout._midi.is_port_open())
        del self.midiout._midi
        del self.midiout
        
    def gen_qust(self):
        qust = dict()
        box_idx = 0
        for row in range(self.row):
            y = row * self.h
            # y = self.calc_box_pos(row_idx, self.h)
            for col in range(self.col):
                x = col * self.w
                box = pg.Surface((self.w - FRAME_WIDTH, self.h - FRAME_WIDTH))
                box.fill(self.rgb)
                # x = self.calc_box_pos(col_idx, self.w)
                # set black transparent
                box.set_colorkey((0, 0, 0))
                qust[box_idx] = (box, (x, y))
                box_idx += 1
        return qust

    # def calc_box_pos(self, idx, box_side):
    #     return ((2 * idx + 1) * FRAME_WIDTH) + (idx * box_side)
    
    def handle_setup_state(self, setup_play_state):
        for cmd in setup_play_state:
            if cmd[0] == KEYWORDS["tempo"]:
                self.timer_ms = bpm_to_ms(cmd[1])
                pg.time.set_timer(self.timer_id, self.timer_ms)
            elif cmd[0] == KEYWORDS["red"]:
                self.rgb[0] = cmd[1]
            elif cmd[0] == KEYWORDS["green"]:
                self.rgb[1] = cmd[1]
            elif cmd[0] == KEYWORDS["blue"]:
                self.rgb[2] = cmd[1]
                
    def handle_play_state(self, play_state):
        """play_state is a concated str '00110110101'"""
        box_idx = 0
        for row in play_state:
            # lights, midi_cmd = row
            # midi_cmd = parse_izip_midi(midi_cmd)
            for col in row:
                if col == "0":
                    self.qust[box_idx][0].fill(BLACK)
                elif col == "1":
                    self.qust[box_idx][0].fill(self.rgb)
                else:
                    raise RuntimeError("Invalid light status {}".format(col))
                box_idx += 1

    def handle_play_state_with_midi(self, play_state):
        """play_state is a concated str '00110110101'"""
        box_idx = 0
        for row in play_state:
            lights, midi_cmd = row
            midi_cmd = parse_izip_midi(midi_cmd)
            for light in lights:
                if light == "0":
                    self.qust[box_idx][0].fill(BLACK)
                    note = self.midi_record[box_idx]
                    # p = self.midi_record[box_idx]
                    if note:
                        p, c = note["p"], note["c"]
                        self.midiout.note_off(p, ch=c)
                        # self.midiout.note_off(p, ch=box_idx+1)
                elif light == "1":
                    # Midi
                    try:
                        p, v, c = [int(x) for x in next(midi_cmd)]
                        self.midiout.note_on(p, v, ch=c)
                    except StopIteration:
                        print "Empty line"
                    # self.midi_record[box_idx] = p
                    self.midi_record[box_idx] = {"p": p, "c": c, "v": v}
                    # Light
                    self.qust[box_idx][0].fill(self.rgb)
                else:
                    raise RuntimeError("Invalid light status {}".format(light))
                box_idx += 1
                
    def draw(self):
        for box_idx, box_pack in self.qust.items():
            box, pos = box_pack
            self.win.blit(box, pos)
    
    def tick(self, pygame_event, print_states=False):
        if pygame_event.type == self.timer_id:
            try:
                state = next(self.runtimes)
                setup_state = filter(lambda t: t[0].startswith(
                    ("BPM", "R", "G", "B")), state)
                play_state = filter(lambda t: t[0].startswith(("0", "1")), state)
                self.handle_setup_state(setup_state)
                if self.with_midi:
                    self.handle_play_state_with_midi(play_state)
                else:
                    self.handle_play_state(play_state)
            except StopIteration:
                if print_states:
                    print "qust-{} done - - -".format(self.id_)
		# shut timer down
		pg.time.set_timer(self.timer_id, 0)
