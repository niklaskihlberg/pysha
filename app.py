import json
import os
import platform
import time

import cairo
import mido
import numpy
import push2_python

import definitions
from main_controls_mode import MainControlsMode
from melodic_mode import MelodicMode
from rhythmic_mode import RhythmicMode
from settings_mode import SettingsMode


class PyshaApp(object):

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

    # frame rate measurements
    actual_frame_rate = 0
    current_frame_rate_measurement = 0
    current_frame_rate_measurement_second = 0

    # other state vars
    active_modes = []
    previously_active_mode_for_xor_group = {}
    pads_need_update = True
    buttons_need_update = True

    # notifications
    notification_text = None
    notification_time = 0

    def __init__(self):
        if os.path.exists('settings.json'):
            settings = json.load(open('settings.json'))
        else:
            settings = {}

        self.set_midi_in_channel(settings.get('midi_in_default_channel', 0))
        self.set_midi_out_channel(settings.get('midi_out_default_channel', 0))
        self.target_frame_rate = settings.get('target_frame_rate', 60)
        self.use_push2_display = settings.get('use_push2_display', True)

        self.init_midi_in(device_name=settings.get('default_midi_in_device_name', None))
        self.init_midi_out(device_name=settings.get('default_midi_out_device_name', None))
        self.init_push()

        self.init_modes(settings)
        # self.toggle_melodic_rhythmic_modes()

    def init_modes(self, settings):
        self.main_controls_mode = MainControlsMode(self, settings=settings)
        self.active_modes.append(self.main_controls_mode)

        self.melodic_mode = MelodicMode(self, settings=settings)
        self.rhyhtmic_mode = RhythmicMode(self, settings=settings)
        self.set_melodic_mode()

        self.settings_mode = SettingsMode(self, settings=settings)

    def get_all_modes(self):
        return [getattr(self, element) for element in vars(self) if isinstance(getattr(self, element), definitions.PyshaMode)]

    def is_mode_active(self, mode):
        return mode in self.active_modes

    def toggle_and_rotate_settings_mode(self):
        if self.is_mode_active(self.settings_mode):
            rotation_finished = self.settings_mode.move_to_next_page()
            if rotation_finished:
                self.active_modes = [mode for mode in self.active_modes if mode != self.settings_mode]
                self.settings_mode.deactivate()
        else:
            self.active_modes.append(self.settings_mode)
            self.settings_mode.activate()

    # def set_mode_for_xor_group(self, mode_to_set):
    #     '''This activates the mode_to_set, but makes sure that if any other modes are currently activated
    #     for the same xor_group, these other modes get deactivated. This also stores a reference to the
    #     latest active mode for xor_group, so once a mode gets unset, the previously active one can be
    #     automatically set'''
    #
    #     if not self.is_mode_active(mode_to_set):
    #
    #         # First deactivate all existing modes for that xor group
    #         new_active_modes = []
    #         for mode in self.active_modes:
    #             if mode.xor_group is not None and mode.xor_group == mode_to_set.xor_group:
    #                 mode.deactivate()
    #                 self.previously_active_mode_for_xor_group[
    #                     mode.xor_group] = mode  # Store last mode that was active for the group
    #             else:
    #                 new_active_modes.append(mode)
    #         self.active_modes = new_active_modes
    #
    #         # Now add the mode to set to the active modes list and activate it
    #         new_active_modes.append(mode_to_set)
    #         mode_to_set.activate()
    #
    # def unset_mode_for_xor_group(self, mode_to_unset):
    #     """This deactivates the mode_to_unset and reactivates the previous mode that was active for this xor_group.
    #     This allows to make sure that one (and only one) mode will be always active for a given xor_group."""
    #
    #     if self.is_mode_active(mode_to_unset):
    #
    #         # Deactivate the mode to unset
    #         self.active_modes = [mode for mode in self.active_modes if mode != mode_to_unset]
    #         mode_to_unset.deactivate()
    #
    #         # Activate the previous mode that was activated for the same xor_group. If none listed, activate a default one
    #         previous_mode = self.previously_active_mode_for_xor_group.get(mode_to_unset.xor_group, None)
    #         if previous_mode is not None:
    #             del self.previously_active_mode_for_xor_group[mode_to_unset.xor_group]
    #             self.set_mode_for_xor_group(previous_mode)
    #         else:
    #             # Enable default
    #             # tod o: here we hardcoded the default mode for a specific xor_group, I should clean this a little bit in the future...
    #             if mode_to_unset.xor_group == 'pads':
    #                 self.set_mode_for_xor_group(self.melodic_mode)

    def toggle_melodic_rhythmic_modes(self):
        if self.is_mode_active(self.melodic_mode):
            self.set_rhythmic_mode()
        elif self.is_mode_active(self.rhyhtmic_mode):
            self.set_melodic_mode()
        else:
            # If none of melodic or rhythmic modes were active, enable melodic by default
            self.set_melodic_mode()

    def set_melodic_mode(self):
        if self.is_mode_active(self.rhyhtmic_mode):
            self.toggle_melodic_rhythmic_modes()

    def set_rhythmic_mode(self):
        if self.is_mode_active(self.melodic_mode):
            self.toggle_melodic_rhythmic_modes()

    def save_current_settings_to_file(self):
        settings = {
            'midi_in_default_channel': self.midi_in_channel,
            'midi_out_default_channel': self.midi_out_channel,
            'default_midi_in_device_name': self.midi_in.name if self.midi_in is not None else None,
            'default_midi_out_device_name': self.midi_out.name if self.midi_out is not None else None,
            'use_push2_display': self.use_push2_display,
            'target_frame_rate': self.target_frame_rate,
        }
        for mode in self.get_all_modes():
            mode_settings = mode.get_settings_to_save()
            if mode_settings:
                settings.update(mode_settings)
        json.dump(settings, open('settings.json', 'w'))

    def init_midi_in(self, device_name=None):
        print('Configuring MIDI in...')
        # noinspection PyUnresolvedReferences
        self.available_midi_in_device_names = [name for name in mido.get_input_names() if not any([banned_names in name for banned_names in ["Ableton Push", "Midi Through", "RtMidi"]])]
        # self.available_midi_in_device_names = [name for name in mido.get_input_names() if 'Ableton Push' not in name]

        if device_name is not None:
            if self.midi_in is not None:
                self.midi_in.callback = None  # Disable current callback (if any)
            try:
                # noinspection PyUnresolvedReferences
                self.midi_in = mido.open_input(device_name)
                self.midi_in.callback = self.midi_in_handler
                print('Receiving MIDI in from "{0}"'.format(device_name))
            except IOError:
                print('Could not connect to MIDI input port "{0}"\nAvailable device names:'.format(device_name))
                for name in self.available_midi_in_device_names:
                    print(' - {0}'.format(name))
        else:
            if self.midi_in is not None:
                self.midi_in.callback = None  # Disable current callback (if any)
                self.midi_in.close()
                self.midi_in = None

        if self.midi_in is None:
            print('Not receiving from any MIDI input')

    def init_midi_out(self, device_name=None):
        print('Configuring MIDI out...')
        # noinspection PyUnresolvedReferences
        self.available_midi_out_device_names = [name for name in mido.get_output_names() if not any([banned_names in name for banned_names in ["Ableton Push", "Midi Through", "RtMidi", "iConnectAUDIO2+ DIN"]])]

        if device_name is not None:
            try:
                # noinspection PyUnresolvedReferences
                self.midi_out = mido.open_output(device_name)
                print('Will send MIDI to "{0}"'.format(device_name))
            except IOError:
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
        if 0 <= device_idx < len(self.available_midi_in_device_names):
            self.init_midi_in(self.available_midi_in_device_names[device_idx])
        else:
            self.init_midi_in(None)

    def set_midi_out_device_by_index(self, device_idx):
        if 0 <= device_idx < len(self.available_midi_out_device_names):
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
        # This will rule out sysex and other "strange" messages that don't have channel info
        if hasattr(msg, 'channel'):
            # If midi input channel is set to -1 (all) or a specific channel
            if self.midi_in_channel == -1 or msg.channel == self.midi_in_channel:

                # Forward message to the MIDI out
                self.send_midi(msg)

                # Forward the midi message to the active modes
                for mode in self.active_modes:
                    mode.on_midi_in(msg)

    def init_push(self):
        print('Configuring Push...')
        self.push = push2_python.Push2()
        if platform.system() == "Linux":
            # When this app runs in Linux is because it is running on the Raspberrypi
            #  I've overved problems trying to reconnect many times without success on the Raspberrypi, resulting in
            # "ALSA lib seq_hw.c:466:(snd_seq_hw_open) open /dev/snd/seq failed: Cannot allocate memory" issues.
            # A work around is make the reconnection time bigger, but a better solution should probably be found.
            # self.push.set_push2_reconnect_call_interval(2)
            #
            # Is this enough time for the RPI? /N
            self.push.set_push2_reconnect_call_interval(9)

    def update_push2_pads(self):
        for mode in self.active_modes:
            mode.update_pads()

    def update_push2_buttons(self):
        for mode in self.active_modes:
            mode.update_buttons()

    def update_push2_display(self):
        if self.use_push2_display:
            # Prepare cairo canvas
            w, h = push2_python.constants.DISPLAY_LINE_PIXELS, push2_python.constants.DISPLAY_N_LINES
            surface = cairo.ImageSurface(cairo.FORMAT_RGB16_565, w, h)
            ctx = cairo.Context(surface)

            # Call all active modes to write to context
            for mode in self.active_modes:
                mode.update_display(ctx, w, h)

            # Convert cairo data to numpy array and send to push
            buf = surface.get_data()
            frame = numpy.ndarray(shape=(h, w), dtype=numpy.uint16, buffer=buf).transpose()
            self.push.display.display_frame(frame, input_format=push2_python.constants.FRAME_FORMAT_RGB565)
            # surface.write_to_png("screenshot_from_main_app.png")

    def check_for_delayed_actions(self):
        # If MIDI not configured, make sure we try sending messages so it gets configured
        if not self.push.midi_is_configured():
            self.push.configure_midi()

        # Call delayed actions in active modes
        for mode in self.active_modes:
            mode.check_for_delayed_actions()

        if self.pads_need_update:
            self.update_push2_pads()
            self.pads_need_update = False

        if self.buttons_need_update:
            self.update_push2_buttons()
            self.buttons_need_update = False

    def run_loop(self):
        print('Pysha is runnnig...')
        try:
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
                    # print('{0} fps'.format(self.actual_frame_rate))

                # Check if any delayed actions need to be applied
                self.check_for_delayed_actions()

                after_draw_time = time.time()

                # Calculate sleep time to aproximate the target frame rate
                sleep_time = (1.0 / self.target_frame_rate) - (after_draw_time - before_draw_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print('Exiting Pysha...')
            self.push.f_stop.set()

    # noinspection PyMethodMayBeStatic
    def on_midi_push_connection_established(self):
        # Do initial configuration of Push
        print('Doing initial Push config...')

        # Configure custom color palette
        app.push.color_palette = {}
        for count, color_name in enumerate(definitions.COLORS_NAMES):
            app.push.set_color_palette_entry(count, [color_name, color_name], rgb=definitions.get_color_rgb(color_name))
        app.push.reapply_color_palette()

        # Initialize all buttons to black, initialize all pads to off
        app.push.buttons.set_all_buttons_color(color=definitions.BLACK)
        app.push.pads.set_all_pads_to_color(color=definitions.BLACK)

        app.update_push2_buttons()
        app.update_push2_pads()


# Bind push action handlers with class methods
@push2_python.on_encoder_rotated()
def on_encoder_rotated(_, encoder_name, increment):
    try:
        for mode in app.active_modes:
            mode.on_encoder_rotated(encoder_name, increment)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_pad_pressed()
def on_pad_pressed(_, pad_n, pad_ij, velocity):
    try:
        for mode in app.active_modes:
            mode.on_pad_pressed(pad_n, pad_ij, velocity)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_pad_released()
def on_pad_released(_, pad_n, pad_ij, velocity):
    try:
        for mode in app.active_modes:
            mode.on_pad_released(pad_n, pad_ij, velocity)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_pad_aftertouch()
def on_pad_aftertouch(_, pad_n, pad_ij, velocity):
    try:
        for mode in app.active_modes:
            mode.on_pad_aftertouch(pad_n, pad_ij, velocity)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_button_pressed()
def on_button_pressed(_, name):
    try:
        for mode in app.active_modes:
            mode.on_button_pressed(name)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_button_released()
def on_button_released(_, name):
    try:
        for mode in app.active_modes:
            mode.on_button_released(name)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_touchstrip()
def on_touchstrip(_, value):
    try:
        for mode in app.active_modes:
            mode.on_touchstrip(value)
    except NameError:
        print('app object not yet ready!')


@push2_python.on_midi_connected()
def on_midi_connected(_):
    try:
        app.on_midi_push_connection_established()
    except NameError:
        print('app object not yet ready!')


@push2_python.on_sustain_pedal()
def on_sustain_pedal(_, sustain_on):
    try:
        for mode in app.active_modes:
            mode.on_sustain_pedal(sustain_on)
    except NameError:
        print('app object not yet ready!')


# Run app main loop
if __name__ == "__main__":
    app = PyshaApp()
    app.run_loop()
