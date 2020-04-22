import os
import math

# Hardware/mech constants
cmH2OperHPa = 1.02 #1 HPa corresponds to 1.02 centimeters of water
motor_step_pin = 12
motor_dir_pin = 16
motor_reset_pin = 7
motor_sleep_pin = 20
solenoid_pin = 26
mosi = 0
steps_per_turn = 200 #200 or 400 generally, depends on stepper motor
gear_reduction = 5+ 2/11 #for stepper motors with attached gearbox
number_of_teeth = 15 #Number of teeth on the pinion driving the rack
module = 2 #Is a property of the rack and pinion system
cylinder_radius = 34.1 #mm

pitch_diameter = module*number_of_teeth #I got a youtube video about this!
mm_per_step = math.pi*pitch_diameter/(steps_per_turn*gear_reduction)


# motor control
max_steps_per_second = 5000
speed_increase_per_step = 100
