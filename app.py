import push2_python
import mido
import time
import random
import cairo
import numpy
import json
import os
import platform


PAD_STATE_ON = True
PAD_STATE_OFF = False
PAD_LAYOUT_MELODIC = 'melodic'
PAD_LAYOUT_RHYTHMIC = 'rhythmic'
DELAYED_ACTIONS_APPLY_TIME = 1.0  # Encoder changes won't be applied until this time has passed since last moved


class Push2StandaloneControllerApp(object):

    # midi
    midi_out = None
    available_midi_out_device_names = []
    midi_out_channel = 0  # 0-15
    midi_out_tmp_device_idx = None  # This is to store device names while rotating encoders
    
    midi_in = None
    available_midi_in_device_names = []
    midi_in_channel = 0  # 0-15
    midi_in_tmp_device_idx = None  # This is to store device names while rotating encoders
    
    # push
    push = None
    use_push2_display = None
    target_frame_rate = None

    # state
    actual_frame_rate = 0
    current_frame_rate_measurement = 0
    current_frame_rate_measurement_second = 0
    notes_being_played = []
    root_midi_note = 0
    scale_pattern = [True, False, True, False, True, True, False, True, False, True, False, True]
    pad_layout_mode = None
    fixed_velocity_mode = False
    encoders_state = {}
    pads_need_update = True
    buttons_need_update = True
    use_poly_at = False
    rhythmic_notes_matrix = [  # Midi note layout to use for rhythmic layout mode
        [64, 65, 66, 67, 96, 97, 98, 99],
        [60, 61, 62, 63, 92, 93, 94, 95],
        [56, 57, 58, 59, 88, 89, 90, 91],
        [52, 53, 54, 55, 84, 85, 86, 87],
        [48, 49, 50, 51, 80, 81, 82, 83],
        [44, 45, 46, 47, 76, 77, 78, 79],
        [40, 41, 42, 43, 72, 73, 74, 75],
        [36, 37, 38, 39, 68, 69, 70, 71]
    ]
    pyramid_track_button_names_a = [
        push2_python.constants.BUTTON_LOWER_ROW_1,
        push2_python.constants.BUTTON_LOWER_ROW_2,
        push2_python.constants.BUTTON_LOWER_ROW_3,
        push2_python.constants.BUTTON_LOWER_ROW_4,
        push2_python.constants.BUTTON_LOWER_ROW_5,
        push2_python.constants.BUTTON_LOWER_ROW_6,
        push2_python.constants.BUTTON_LOWER_ROW_7,
        push2_python.constants.BUTTON_LOWER_ROW_8
    ]
    pyramid_track_button_names_b = [  
        push2_python.constants.BUTTON_1_32T,
        push2_python.constants.BUTTON_1_32,
        push2_python.constants.BUTTON_1_16T,
        push2_python.constants.BUTTON_1_16,
        push2_python.constants.BUTTON_1_8T,
        push2_python.constants.BUTTON_1_8,
        push2_python.constants.BUTTON_1_4T,
        push2_python.constants.BUTTON_1_4
    ]
    pyramid_track_selection_button_a = False
    selected_pyramid_track = 0


    def __init__(self):
        if os.path.exists('settings.json'):
            settings = json.load(open('settings.json'))
        else:
            settings = {}

        self.set_midi_in_channel(settings.get('midi_in_default_channel', 0))
        self.set_midi_out_channel(settings.get('midi_out_default_channel', 0)) 
        self.use_poly_at = settings.get('use_poly_at', True)        
        self.set_root_midi_note(settings.get('root_midi_note', 64))
        self.target_frame_rate = settings.get('target_frame_rate', 60)
        self.use_push2_display = settings.get('use_push2_display', True)
        self.pad_layout_mode = settings.get('pad_layout_mode', PAD_LAYOUT_MELODIC)

        self.init_midi_in(device_name=settings.get('default_midi_in_device_name', None))
        self.init_midi_out(device_name=settings.get('default_midi_out_device_name', None))
        self.init_push()
        self.init_state()


    def save_current_settings_to_file(self):
        json.dump({
            'midi_in_default_channel': self.midi_in_channel,
            'midi_out_default_channel': self.midi_out_channel,
            'default_midi_in_device_name': self.midi_in.name if self.midi_in is not None else None,
            'default_midi_out_device_name': self.midi_out.name if self.midi_out is not None else None,
            'use_push2_display': self.use_push2_display,
            'target_frame_rate': self.target_frame_rate,
            'use_poly_at': self.use_poly_at,
            'root_midi_note': self.root_midi_note,
            'pad_layout_mode': self.pad_layout_mode
        }, open('settings.json', 'w'))


    def init_midi_in(self, device_name=None):
        print('Configuring MIDI in...')
        self.available_midi_in_device_names = [name for name in mido.get_input_names() if 'Ableton Push' not in name]
        
        if device_name is not None:
            if self.midi_in is not None:
                    self.midi_in.callback = None  # Disable current callback (if any)
            try:
                self.midi_in = mido.open_input(device_name)
                self.midi_in.callback = self.midi_in_handler
                print('Receiving MIDI in from "{0}"'.format(device_name))
            except IOError:
                print('Could not connect to MIDI input port "{0}"\nAvailable device names:'.format(device_name))
                for name in self.available_midi_in_device_names:
                    print(' - {0}'.format(name))
        else:
            if self.midi_in is not None:
                self.midi_in.callback = None # Disable current callback (if any)
                self.midi_in.close()
                self.midi_in = None
            
        if self.midi_in is None:
            print('Not receiving from any MIDI input')


    def init_midi_out(self, device_name=None):
        print('Configuring MIDI out...')
        self.available_midi_out_device_names = [name for name in mido.get_output_names() if 'Ableton Push' not in name]
       
        if device_name is not None:
            try:
                self.midi_out = mido.open_output(device_name)
                print('Will send MIDI to "{0}"'.format(device_name))
            except IOError as e:
                print('Could not connect to MIDI output port "{0}"\nAvailable device names:'.format(device_name))
                for name in self.available_midi_out_device_names:
                    print(' - {0}'.format(name))
        else:
            if self.midi_out is not None:
                self.midi_out.close()
                self.midi_out = None

        if self.midi_out is None:
            print('Won\'t send MIDI to any device')

    
    def set_midi_in_channel(self, channel, wrap=False):
        self.midi_in_channel = channel
        if self.midi_in_channel < -1:  # Use "-1" for "all channels"
            self.midi_in_channel = -1 if not wrap else 15
        elif self.midi_in_channel > 15:
            self.midi_in_channel = 15 if not wrap else -1


    def set_midi_out_channel(self, channel, wrap=False):
        self.midi_out_channel = channel
        if self.midi_out_channel < 0:
            self.midi_out_channel = 0 if not wrap else 15
        elif self.midi_out_channel > 15:
            self.midi_out_channel = 15 if not wrap else 0


    def set_midi_in_device_by_index(self, device_idx):
        if device_idx >= 0 and device_idx < len(self.available_midi_in_device_names):
            self.init_midi_in(self.available_midi_in_device_names[device_idx])
        else:
            self.init_midi_in(None)


    def set_midi_out_device_by_index(self, device_idx):
        if device_idx >= 0 and device_idx < len(self.available_midi_out_device_names):
            self.init_midi_out(self.available_midi_out_device_names[device_idx])
        else:
            self.init_midi_out(None)


    def send_midi(self, msg, force_channel=None):
        if self.midi_out is not None:
            if hasattr(msg, 'channel'):
                channel = force_channel if force_channel is not None else self.midi_out_channel
                msg = msg.copy(channel=channel)  # If message has a channel attribute, update it
            self.midi_out.send(msg)


    def midi_in_handler(self, msg): 

        if hasattr(msg, 'channel'):  # This will rule out sysex and other "strange" messages that don't have channel info
            if self.midi_in_channel == -1 or msg.channel == self.midi_in_channel:   # If midi input channel is set to -1 (all) or a specific channel
             
                # Forward message to the MIDI out
                self.send_midi(msg)
                
                # Update the list of notes being currently played so push2 pads can be updated accordingly
                if msg.type == "note_on":
                    if msg.velocity == 0:
                        self.remove_note_being_played(msg.note, self.midi_in.name)
                    else:
                        self.add_note_being_played(msg.note, self.midi_in.name)
                elif msg.type == "note_off":
                    self.remove_note_being_played(msg.note, self.midi_in.name)
                self.pads_need_update = True  # Using the async update method because we don't really need immediate response here


    def init_push(self):
        print('Configuring Push...')
        self.push = push2_python.Push2()
        if platform.system() == "Linux":
            # When this app runs in Linux is because it is running on the Raspberrypi
            #  I've overved problems trying to reconnect many times withotu success on the Raspberrypi, resulting in
            # "ALSA lib seq_hw.c:466:(snd_seq_hw_open) open /dev/snd/seq failed: Cannot allocate memory" issues.
            # A work around is make the reconnection time bigger, but a better solution should probably be found.
            self.push.set_push2_reconnect_call_interval(2)
        

    def init_state(self):
        current_time = time.time()
        self.last_time_pads_updated = current_time
        self.last_time_buttons_updated = current_time
        for encoder_name in self.push.encoders.available_names:
            self.encoders_state[encoder_name] = {
                'last_message_received': current_time,
            }


    def add_note_being_played(self, midi_note, source):
        self.notes_being_played.append({'note': midi_note, 'source': source})

    
    def remove_note_being_played(self, midi_note, source):
        self.notes_being_played = [note for note in self.notes_being_played if note['note'] != midi_note or note['source'] != source] 
        

    def pad_ij_to_midi_note(self, pad_ij):
        if self.pad_layout_mode == PAD_LAYOUT_MELODIC:
            return self.root_midi_note + ((7 - pad_ij[0]) * 5 + pad_ij[1])
        else:
            return self.rhythmic_notes_matrix[pad_ij[0]][pad_ij[1]]
    
    
    def is_midi_note_root_octave(self, midi_note):
        relative_midi_note = (midi_note - self.root_midi_note) % 12
        return relative_midi_note == 0


    def is_black_key_midi_note(self, midi_note):
        relative_midi_note = (midi_note - self.root_midi_note) % 12
        return not self.scale_pattern[relative_midi_note]


    def is_midi_note_being_played(self, midi_note):
        for note in self.notes_being_played:
            if note['note'] == midi_note:
                return True
        return False

    
    def note_number_to_name(self, note_number):
        semis = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        note_number = int(round(note_number))
        return semis[note_number % 12] + str(note_number//12 - 1)


    def set_root_midi_note(self, note_number):
        self.root_midi_note = note_number
        if self.root_midi_note < 0:
            self.root_midi_note = 0
        elif self.root_midi_note > 127:
            self.root_midi_note = 127


    def update_push2_pads(self):
        color_matrix = []
        for i in range(0, 8):
            row_colors = []
            for j in range(0, 8):
                corresponding_midi_note = self.pad_ij_to_midi_note([i, j])

                if self.pad_layout_mode == PAD_LAYOUT_MELODIC:
                    cell_color = 'white'
                    if self.is_black_key_midi_note(corresponding_midi_note): 
                        cell_color = 'black'
                    if self.is_midi_note_root_octave(corresponding_midi_note):
                        if not self.fixed_velocity_mode:
                            cell_color = 'yellow'
                        else:
                            cell_color = 'blue'
                    if self.is_midi_note_being_played(corresponding_midi_note):
                        cell_color = 'green'
                elif self.pad_layout_mode == PAD_LAYOUT_RHYTHMIC:
                    cell_color = 'black'
                    if i >= 4 and j < 4:
                        if not self.fixed_velocity_mode:
                            cell_color = 'yellow'
                        else:
                            cell_color = 'blue'
                    elif i >= 4 and j >= 4:
                        cell_color = 'turquoise'
                    elif i < 4 and j < 4:
                        cell_color = 'orange'
                    elif i < 4 and j >= 4:
                        cell_color = 'pink'
                    if self.is_midi_note_being_played(corresponding_midi_note):
                        cell_color = 'green'

                row_colors.append(cell_color)
            color_matrix.append(row_colors)
        
        self.push.pads.set_pads_color(color_matrix)
        

    def update_push2_buttons(self):
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_MUTE, 'red')

        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_1, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_2, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_3, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_4, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_5, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_6, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_7, 'green')
        if self.use_push2_display:
            self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_8, 'white')
        else:
            self.push.buttons.set_button_color(push2_python.constants.BUTTON_UPPER_ROW_8, 'red')
        
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_OCTAVE_DOWN, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_OCTAVE_UP, 'white')
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_NOTE, 'white')

        for count, name in enumerate(self.pyramid_track_button_names_a):
            if self.selected_pyramid_track % 8 == count:
                self.push.buttons.set_button_color(name, 'green')
            else:
                self.push.buttons.set_button_color(name, 'orange')

        for count, name in enumerate(self.pyramid_track_button_names_b):
            if self.pyramid_track_selection_button_a:
                if self.selected_pyramid_track // 8 == count:
                    self.push.buttons.set_button_color(name, 'green')
                else:
                    self.push.buttons.set_button_color(name, 'orange')
            else:
                self.push.buttons.set_button_color(name, 'black')
    
        self.push.buttons.set_button_color(push2_python.constants.BUTTON_ACCENT, 'green')
        

    def generate_display_frame(self):

        def show_title(x, text, color=[1, 1, 1]):
            text = str(text)
            ctx.set_source_rgb(*color)
            ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            font_size = h//12
            ctx.set_font_size(font_size)
            ctx.move_to(x + 3, 20)
            ctx.show_text(text)

        def show_value(x, text, color=[1, 1, 1]):
            text = str(text)
            ctx.set_source_rgb(*color)
            ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            font_size = h//8
            ctx.set_font_size(font_size)
            ctx.move_to(x + 3, 45)
            ctx.show_text(text)

        # Prepare cairo canvas
        w, h = push2_python.constants.DISPLAY_LINE_PIXELS, push2_python.constants.DISPLAY_N_LINES
        surface = cairo.ImageSurface(cairo.FORMAT_RGB16_565, w, h)
        ctx = cairo.Context(surface)

        # Divide display in 8 parts to show different settings
        part_w = w // 8
        part_h = h
        for i in range(0, 8):
            part_x = i * part_w 
            part_y = 0

            ctx.set_source_rgb(0, 0, 0)  # Draw black background
            ctx.rectangle(part_x - 3, part_y, w, h)  # do x -3 to add some margin between parts
            ctx.fill()

            color = [1.0, 1.0, 1.0]
            
            if i==0:  # MIDI in device
                if self.midi_in_tmp_device_idx is not None:
                    color = [1.0, 0.64, 0.0]  # Orange font
                    if self.midi_in_tmp_device_idx < 0:
                        name = "None"
                    else:
                        name = "{0} {1}".format(self.midi_in_tmp_device_idx + 1, self.available_midi_in_device_names[self.midi_in_tmp_device_idx])
                else:
                    if self.midi_in is not None:
                        name = "{0} {1}".format(self.available_midi_in_device_names.index(self.midi_in.name) + 1, self.midi_in.name)
                    else:
                        color = [0.5, 0.5, 0.5]  # Gray font
                        name = "None"
                show_title(part_x, 'IN DEVICE')
                show_value(part_x, name, color)
                
            elif i==1:  # MIDI in channel
                if self.midi_in is None:
                    color = [0.5, 0.5, 0.5]  # Gray font
                show_title(part_x, 'IN CH')
                show_value(part_x, self.midi_in_channel + 1 if self.midi_in_channel > -1 else "All", color)

            elif i==2:  # MIDI out device
                if self.midi_out_tmp_device_idx is not None:
                    color = [1.0, 0.64, 0.0]  # Orange font
                    if self.midi_out_tmp_device_idx < 0:
                        name = "None"
                    else:
                        name = "{0} {1}".format(self.midi_out_tmp_device_idx + 1, self.available_midi_out_device_names[self.midi_out_tmp_device_idx])
                else:
                    if self.midi_out is not None:
                        name = "{0} {1}".format(self.available_midi_out_device_names.index(self.midi_out.name) + 1, self.midi_out.name)
                    else:
                        color = [0.5, 0.5, 0.5]  # Gray font
                        name = "None"
                show_title(part_x, 'OUT DEVICE')
                show_value(part_x, name, color)

            elif i==3:  # MIDI out channel
                if self.midi_out is None:
                    color = [0.5, 0.5, 0.5]  # Gray font
                show_title(part_x, 'OUT CH')
                show_value(part_x, self.midi_out_channel + 1, color)

            elif i==4:  # Root note
                if self.pad_layout_mode == PAD_LAYOUT_RHYTHMIC:
                    color = [0.5, 0.5, 0.5]  # Gray font
                show_title(part_x, 'ROOT NOTE')
                show_value(part_x, "{0} ({1})".format(self.note_number_to_name(self.root_midi_note), self.root_midi_note), color)

            elif i==5:  # Poly AT/channel AT
                show_title(part_x, 'AFTERTOUCH')
                show_value(part_x, 'polyAT' if self.use_poly_at else 'channel', color)

            elif i==6:  # Save button
                show_title(part_x, 'SAVE')
            elif i==7:  # FPS indicator
                show_title(part_x, 'FPS')
                show_value(part_x, self.actual_frame_rate, color)

        buf = surface.get_data()
        return numpy.ndarray(shape=(h, w), dtype=numpy.uint16, buffer=buf).transpose()


    def check_for_delayed_actions(self):
        current_time = time.time()

        if self.midi_in_tmp_device_idx is not None:
            # Means we are in the process of changing the MIDI in device
            if current_time - self.encoders_state[push2_python.constants.ENCODER_TRACK1_ENCODER]['last_message_received'] > DELAYED_ACTIONS_APPLY_TIME:
                self.set_midi_in_device_by_index(self.midi_in_tmp_device_idx)
                self.midi_in_tmp_device_idx = None

        if self.midi_out_tmp_device_idx is not None:
            # Means we are in the process of changing the MIDI in device
            if current_time - self.encoders_state[push2_python.constants.ENCODER_TRACK3_ENCODER]['last_message_received'] > DELAYED_ACTIONS_APPLY_TIME:
                self.set_midi_out_device_by_index(self.midi_out_tmp_device_idx)
                self.midi_out_tmp_device_idx = None

        if not self.push.midi_is_configured():  # If MIDI not configured, make sure we try sending messages so it gets configured
            self.push.configure_midi()

        if self.pads_need_update:
            self.update_push2_pads()
            self.pads_need_update = False

        if self.buttons_need_update:
            self.update_push2_buttons()
            self.buttons_need_update = False


    def update_push2_display(self):
        if self.use_push2_display:
            frame = self.generate_display_frame()
            self.push.display.display_frame(frame, input_format=push2_python.constants.FRAME_FORMAT_RGB565)


    def run_loop(self):
        print('App runnnig...')
        while True:
            before_draw_time = time.time()
            
            # Draw ui
            self.update_push2_display()
            
            # Frame rate measurement
            now = time.time()
            self.current_frame_rate_measurement += 1
            if time.time() - self.current_frame_rate_measurement_second > 1.0:
                self.actual_frame_rate = self.current_frame_rate_measurement
                self.current_frame_rate_measurement = 0
                self.current_frame_rate_measurement_second = now
                print('{0} fps'.format(self.actual_frame_rate))
            
            # Check if any delayed actions need to be applied
            self.check_for_delayed_actions()

            after_draw_time = time.time()

            # Calculate sleep time to aproximate the target frame rate
            sleep_time = (1.0 / self.target_frame_rate) - (after_draw_time - before_draw_time)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def on_midi_push_connection_established(self):
        # Do initial configuration of Push
        print('Doing initial Push config...')
        app.update_push2_buttons()
        app.update_push2_pads()
        if self.use_poly_at:
            app.push.pads.set_polyphonic_aftertouch()
        else:
            app.push.pads.set_channel_aftertouch()

    def on_encoder_rotated(self, encoder_name, increment):

        self.encoders_state[encoder_name]['last_message_received'] = time.time()

        if encoder_name == push2_python.constants.ENCODER_TRACK1_ENCODER:
            if self.midi_in_tmp_device_idx is None:
                if self.midi_in is not None:
                    self.midi_in_tmp_device_idx = self.available_midi_in_device_names.index(self.midi_in.name)
                else:
                    self.midi_in_tmp_device_idx = -1
            self.midi_in_tmp_device_idx += increment
            if self.midi_in_tmp_device_idx >= len(self.available_midi_in_device_names):
                self.midi_in_tmp_device_idx = len(self.available_midi_in_device_names) - 1
            elif self.midi_in_tmp_device_idx < -1:
                self.midi_in_tmp_device_idx = -1  # Will use -1 for "None"
        
        elif encoder_name == push2_python.constants.ENCODER_TRACK2_ENCODER:
            self.set_midi_in_channel(self.midi_in_channel + increment, wrap=False)
        
        elif encoder_name == push2_python.constants.ENCODER_TRACK3_ENCODER:
            if self.midi_out_tmp_device_idx is None:
                if self.midi_out is not None:
                    self.midi_out_tmp_device_idx = self.available_midi_out_device_names.index(self.midi_out.name)
                else:
                    self.midi_out_tmp_device_idx = -1
            self.midi_out_tmp_device_idx += increment
            if self.midi_out_tmp_device_idx >= len(self.available_midi_out_device_names):
                self.midi_out_tmp_device_idx = len(self.available_midi_out_device_names) - 1
            elif self.midi_out_tmp_device_idx < -1:
                self.midi_out_tmp_device_idx = -1  # Will use -1 for "None"
        
        elif encoder_name == push2_python.constants.ENCODER_TRACK4_ENCODER:
            self.set_midi_out_channel(self.midi_out_channel + increment, wrap=False)
        
        elif encoder_name == push2_python.constants.ENCODER_TRACK5_ENCODER:
            self.set_root_midi_note(self.root_midi_note + increment)
            self.pads_need_update = True  # Using async update method because we don't really need immediate response here

        elif encoder_name == push2_python.constants.ENCODER_TRACK6_ENCODER:
            if increment >= 3:  # Only respond to "big" increments
                if not self.use_poly_at:
                    self.use_poly_at = True
                    self.push.pads.set_polyphonic_aftertouch()
            elif increment <= -3:
                if self.use_poly_at:
                    self.use_poly_at = False
                    self.push.pads.set_channel_aftertouch()

    def on_button_pressed(self, button_name):
        
        if button_name == push2_python.constants.BUTTON_UPPER_ROW_1:
            if self.midi_in_tmp_device_idx is None:
                if self.midi_in is not None:
                    self.midi_in_tmp_device_idx = self.available_midi_in_device_names.index(self.midi_in.name)
                else:
                    self.midi_in_tmp_device_idx = -1
            self.midi_in_tmp_device_idx += 1
            # Make index position wrap
            if self.midi_in_tmp_device_idx >= len(self.available_midi_in_device_names):
                self.midi_in_tmp_device_idx = -1  # Will use -1 for "None"
            elif self.midi_in_tmp_device_idx < -1:
                self.midi_in_tmp_device_idx = len(self.available_midi_in_device_names) - 1

        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_2:
            self.set_midi_in_channel(self.midi_in_channel + 1, wrap=True)

        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_3:
            if self.midi_out_tmp_device_idx is None:
                if self.midi_out is not None:
                    self.midi_out_tmp_device_idx = self.available_midi_out_device_names.index(self.midi_out.name)
                else:
                    self.midi_out_tmp_device_idx = -1
            self.midi_out_tmp_device_idx += 1
            # Make index position wrap
            if self.midi_out_tmp_device_idx >= len(self.available_midi_out_device_names):
                self.midi_out_tmp_device_idx = -1  # Will use -1 for "None"
            elif self.midi_out_tmp_device_idx < -1:
                self.midi_out_tmp_device_idx = len(self.available_midi_out_device_names) - 1
            
        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_4:
            self.set_midi_out_channel(self.midi_out_channel + 1, wrap=True)

        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_5:
            self.set_root_midi_note(self.root_midi_note + 1)
            self.pads_need_update = True

        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_6:
            self.use_poly_at = not self.use_poly_at
            if self.use_poly_at:
                self.push.pads.set_polyphonic_aftertouch()
            else:
                self.push.pads.set_channel_aftertouch()

        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_7:
            # Save current settings
            app.save_current_settings_to_file()

        elif button_name == push2_python.constants.BUTTON_UPPER_ROW_8:
            # Toogle use display
            self.use_push2_display = not self.use_push2_display
            if not self.use_push2_display:
                self.push.display.send_to_display(self.push.display.prepare_frame(self.push.display.make_black_frame()))
            self.buttons_need_update = True

        elif button_name == push2_python.constants.BUTTON_OCTAVE_UP:
            self.set_root_midi_note(self.root_midi_note + 12)
            self.pads_need_update = True  # Using async update method because we don't really need immediate response here

        elif button_name == push2_python.constants.BUTTON_OCTAVE_DOWN:
            self.set_root_midi_note(self.root_midi_note - 12)
            self.pads_need_update = True  # Using async update method because we don't really need immediate response here

        elif button_name == push2_python.constants.BUTTON_NOTE:
            if self.pad_layout_mode == PAD_LAYOUT_MELODIC:
                self.pad_layout_mode = PAD_LAYOUT_RHYTHMIC
            else:
                self.pad_layout_mode = PAD_LAYOUT_MELODIC
            self.pads_need_update = True

        elif button_name in self.pyramid_track_button_names_a:
            self.pyramid_track_selection_button_a = button_name
            self.buttons_need_update = True

        elif button_name in self.pyramid_track_button_names_b:
            if self.pyramid_track_selection_button_a:
                self.selected_pyramid_track = self.pyramid_track_button_names_a.index(self.pyramid_track_selection_button_a) + self.pyramid_track_button_names_b.index(button_name) * 8
                self.buttons_need_update = True
                self.send_select_track_to_pyramid(self.selected_pyramid_track)
                self.pyramid_track_selection_button_a = False

        elif button_name == push2_python.constants.BUTTON_ACCENT:
            self.fixed_velocity_mode = not self.fixed_velocity_mode
            self.buttons_need_update = True     
            self.pads_need_update = True

        elif button_name == push2_python.constants.BUTTON_MUTE:
            # Send MIDI 
            self.notes_being_played = []
            self.pads_need_update = True
            if self.midi_out is not None:
                self.midi_out.panic()

    def on_button_released(self, button_name):
        if button_name in self.pyramid_track_button_names_a:
            if self.pyramid_track_selection_button_a:
                self.pyramid_track_selection_button_a = False
                self.buttons_need_update = True
                self.selected_pyramid_track = self.pyramid_track_button_names_a.index(button_name)
                self.send_select_track_to_pyramid(self.selected_pyramid_track)
            

    def on_pad_pressed(self, pad_n, pad_ij, velocity):
        midi_note = self.pad_ij_to_midi_note(pad_ij)
        if midi_note is not None:
            self.add_note_being_played(midi_note, 'push')
            msg = mido.Message('note_on', note=midi_note, velocity=velocity if not self.fixed_velocity_mode else 127)
            self.send_midi(msg)
            self.update_push2_pads()  # Directly calling update pads method because we want user to feel feedback as quick as possible

    def on_pad_released(self, pad_n, pad_ij, velocity):
        midi_note = self.pad_ij_to_midi_note(pad_ij)
        if midi_note is not None:
            self.remove_note_being_played(midi_note, 'push')
            msg = mido.Message('note_off', note=midi_note, velocity=velocity)
            self.send_midi(msg)
            self.update_push2_pads()  # Directly calling update pads method because we want user to feel feedback as quick as possible

    def on_pad_aftertouch(self, pad_n, pad_ij, velocity):
        if pad_n is not None:
            # polyAT mode
            midi_note = self.pad_ij_to_midi_note(pad_ij)
            if midi_note is not None:
                msg = mido.Message('polytouch', note=midi_note, value=velocity)
        else:
            # channel AT mode
            msg = mido.Message('aftertouch', value=velocity)
        self.send_midi(msg)

    def on_touchstrip(self, value):
        msg = mido.Message('pitchwheel', pitch=value)
        self.send_midi(msg)

    def on_sustain_pedal(self, sustain_on):
        msg = mido.Message('control_change', control=64, value=127 if sustain_on else 0)
        self.send_midi(msg)

    def send_select_track_to_pyramid(self, track_idx):
        # Follows pyramidi specification (Pyramid configured to receive on ch 16)
        msg = mido.Message('control_change', control=0, value=track_idx + 1)
        self.send_midi(msg, force_channel=15)


# Set up action handlers to react to encoder touches and rotation
@push2_python.on_encoder_rotated()
def on_encoder_rotated(push, encoder_name, increment):
    app.on_encoder_rotated(encoder_name, increment)


# Set up action handlers to react to pads being pressed and released
@push2_python.on_pad_pressed()
def on_pad_pressed(push, pad_n, pad_ij, velocity):
    app.on_pad_pressed(pad_n, pad_ij, velocity)


@push2_python.on_pad_released()
def on_pad_released(push, pad_n, pad_ij, velocity):
    app.on_pad_released(pad_n, pad_ij, velocity)


@push2_python.on_pad_aftertouch()
def on_pad_aftertouch(push, pad_n, pad_ij, velocity):
    app.on_pad_aftertouch(pad_n, pad_ij, velocity)


@push2_python.on_button_pressed()
def on_button_pressed(push, name):
    app.on_button_pressed(name)


@push2_python.on_button_released()
def on_button_released(push, name):
    app.on_button_released(name)


@push2_python.on_touchstrip()
def on_touchstrip(push, value):
    app.on_touchstrip(value)


@push2_python.on_midi_connected()
def on_midi_connected(push):
    app.on_midi_push_connection_established()
    

@push2_python.on_sustain_pedal()
def on_sustain_pedal(push, sustain_on):
    app.on_sustain_pedal(sustain_on)


if __name__ == "__main__":
    app = Push2StandaloneControllerApp()
    app.run_loop()
