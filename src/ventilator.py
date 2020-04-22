"""
First attempt at making a ventilator for supplying oxygen to patients
suffering from ARDS. Impetus for development was the Covid-19 pandemic.
Program consists roughly of 3 parallel processes:
1) main process runs Tkinter GUI
2) Measures all sensors periodically
3) Moves motor to where it should go

CODE AND DESIGN PROVIDED AS IS, WITHOUT ANY WARRENTY OF ANY KIND.
USE ONLY AS ABSOLUTE LAST RESORT.
"""

import tkinter as tk
import pigpio
import time
import math
import multiprocessing as mp
import os
import busio
import adafruit_bme280
import digitalio
import board
import settings as s # named constants 

#physics:
sensor1pin = digitalio.DigitalInOut(board.D5)
sensor2pin = digitalio.DigitalInOut(board.D6)

# define and import hardware constants
pitch_diameter = s.module*s.number_of_teeth #I got a youtube video about this!
mm_per_step = math.pi*s.pitch_diameter/(s.steps_per_turn*s.gear_reduction)

refresh_rate = 30 #how many times per second to update UI
update_time = math.floor(1000/refresh_rate) #1/refreshrate, *1000 for milliseconds

#objects and modes setup:
pi = pigpio.pi()
root = tk.Tk()
root.tk.call('tk', 'scaling', 2.0)
spi = busio.SPI(board.SCK, MOSI = board.MOSI, MISO = board.MISO)
pressure_sensor_ambient = adafruit_bme280.Adafruit_BME280_SPI(spi, sensor1pin)
pressure_sensor_ambient.mode = adafruit_bme280.MODE_NORMAL
pressure_sensor_ambient.standby_period = adafruit_bme280.STANDBY_TC_10
pressure_sensor_patient = adafruit_bme280.Adafruit_BME280_SPI(spi, sensor2pin)
pressure_sensor_patient.mode = adafruit_bme280.MODE_NORMAL
pressure_sensor_patient.standby_period = adafruit_bme280.STANDBY_TC_10

#setting up some of the pins:
pi.set_mode(s.motor_step_pin, pigpio.OUTPUT)
pi.set_mode(s.motor_dir_pin, pigpio.OUTPUT)
pi.set_mode(s.motor_sleep_pin, pigpio.OUTPUT)
pi.set_mode(s.motor_reset_pin, pigpio.OUTPUT)

#setting up some multiprocessing shared variables
last_step_count = mp.Value('i', 0) #incremental position in stepper motor steps
move_direction = mp.Value('i', 0) #in what direction the stepper is moving
last_pressure_gauge = mp.Value('f', 0) #Difference between outside and inside, corrected for sensor error
last_pressure_gauge_raw = mp.Value('f', 0) #Difference between ouside and inside before correction
last_pressure_patient = mp.Value('f', 0) #absolute pressure patient side
last_pressure_ambient = mp.Value('f', 0) #absolute ambient pressure
pressure_offset = mp.Value('f', 0) #difference in reading between the 2 sensors
                                #when the actual difference is 0
target_distance = mp.Value('f', 0)
target_steps = mp.Value('i', 0)
PEEP = mp.Value('f', 0)

#measure sensor values for a while to figure out what the offset between the
#two is
def calibrate_pressure_sensor():
    start = time.time()
    pressure_values = []
    while time.time() - start < 5:
        pressure_values.append(last_pressure_gauge_raw.value)
        time.sleep(0.02)
    #print(pressurevalues)
    pressure_offset.value = sum(pressure_values)/len(pressure_values)
    win.CalibrationValue.set(pressure_offset.value)

#Take values from UI and actually insert and use them
def set_values():
    pass

#Take current set values and insert them into UI, discarding changes made
def discard_changes():
    pass


def increment_dist(gpio, level, tick):
    timestamp = time.time()
    if move_direction.value == 0:
        last_step_count.value -= 1
    else:
        last_step_count.value += 1

#one process to continually measure the pressure
def read_sensor_continuous():
    while True:
        timestamp = time.time()
        ambient_pressure = pressure_sensor_ambient.pressure
        patient_pressure = pressure_sensor_patient.pressure
        pressure_difference = patient_pressure - ambient_pressure
        gauge_pressure = pressure_difference - pressure_offset.value
        last_pressure_ambient.value = ambient_pressure
        last_pressure_patient.value = patient_pressure
        last_pressure_gauge_raw.value = pressure_difference
        last_pressure_gauge.value = gauge_pressure
        time.sleep(0.01)

#one process to control the motor
def motor_control():
    current_steps_per_second = 0
    current_direction = 0 #0 for backwards, 1 for fowards (air into patient)
    max_steps_per_second = 5000
    update_time = 0.01
    acceleration_step_time = update_time
    speed_increase_per_step = 100 #steps/s to add per updatetime
    acceleration = speed_increase_per_step/acceleration_step_time #in steps/s/s
    max_decel = 2*acceleration
    total_acceleration_steps = max_steps_per_second
    acceptable_steps_error = 5

    pi.write(MotorSleepPin, True)
    pi.write(MotorResetPin, True)
    while True:
        steps_to_go = target_steps.value - last_step_count.value #can be + or -
        #first check we're going in the right direction to begin with.
        if steps_to_go > 0 and current_direction == 0 or \
            steps_to_go < 0 and current_direction == 1: #slow down and reverse
            #print("reversing 0 to 1")
            current_steps_per_second -= speed_increase_per_step
            if current_steps_per_second < 0:
                current_steps_per_second = 0
                if current_direction == 0:
                    current_direction = 1
                else:
                    current_direction = 0
##        elif steps_to_go < 0 and current_direction == 1:
##            print("reversing 1 to 0")
##            current_steps_per_second -= speed_increase_per_step
##            if current_steps_per_second < 0:
##                current_steps_per_second = 0
##                current_direction = 0
        else: #if we are going in the right direction
            decel_ticks = acceleration_step_time*(current_steps_per_second/speed_increase_per_step)
            decel_dist = 0.5*current_steps_per_second**2/acceleration #how much further do we go if we brake now
            if decel_dist >= abs(steps_to_go): #time to slow down
                
                if steps_to_go == 0:
                    deceleration = max_decel
                else:
                    deceleration = abs(0.5*current_steps_per_second**2/steps_to_go)
                if deceleration > max_decel:
                    deceleration = max_decel
                #print("decelerating", deceldist, current_steps_per_second, steps_to_go, deceleration)
                current_steps_per_second -= int(deceleration*acceleration_step_time)
                if current_steps_per_second < 0:
                    current_steps_per_second = 0
                    if current_direction == 0:
                        current_direction = 1
                    else:
                        current_direction = 0
            #if we're too far off the target, and we shouldn't slow down yet, speed up
            elif abs(steps_to_go) > acceptable_steps_error:
                #print("accelerating", current_steps_per_second, steps_to_go)
                current_steps_per_second += speed_increase_per_step 
                if current_steps_per_second > max_steps_per_second:
                    current_steps_per_second = max_steps_per_second
        #print(current_direction, current_steps_per_second)
        move_direction.value = current_direction
        pi.write(s.motor_dir_pin, current_direction)
        pi.hardware_PWM(s.motor_step_pin, current_steps_per_second, 500000)
        time.sleep(update_time)
            
        
#one process to control the breathing rhythem
def breathe_control():
    while True:
        PEEP.value = 5
        target_distance.value = 150
        target_steps.value = int(target_distance.value/mm_per_step)
        print("Inspiring")
        time.sleep(1)
        print("Exhaling")
        target_distance.value = 0
        target_steps.value = 0
        expiration_start = time.time()
        if last_pressure_gauge.value > PEEP.value:
            print("Waiting for pressure to drop to PEEP", last_pressure_gauge.value, PEEP.value)
            pi.write(s.solenoid_pin, True)
            print("Solenoid open", time.time())
            while last_pressure_gauge.value > PEEP.value and \
                  time.time() - expiration_start < 2:
                time.sleep(0.001)
        
        print("Closing Solenoid", time.time())
        pi.write(s.solenoid_pin, False)
        while time.time() - expiration_start < 2:
            time.sleep(0.001)
        #time.sleep(0.001)        
##        #wait for trigger, either from pressure or time
##        #record time, push piston, monitor pressure
##        now = time.time()
##        move_direction.value = 1
##        pi.write(MotorDirPin, move_direction.value)
##        pi.hardware_PWM(MotorStepPin, 500, 500000)
##        time.sleep(0.5)
##        pi.hardware_PWM(MotorStepPin, 0, 500000)
##        time.sleep(0.5)
##        move_direction.value = 0
##        pi.write(MotorDirPin, move_direction.value)
##        pi.hardware_PWM(MotorStepPin, 500, 500000)
##        time.sleep(0.5)
##        pi.hardware_PWM(MotorStepPin, 0, 500000)
##        time.sleep(0.5)
##        #open exhaust valve
##        #withdraw piston, monitor pressure, apply PEEP
##        #having an endstop for that would add reliability
##        #if PEEP not yet reached, wait for that


#and the final main process runs the tkinter mainloop
def update():
    pressure = last_pressure_gauge.value*s.cmH2OperHPa
    win.pressurelabel.configure(text = f'{pressure:.1f}cm')
    position = last_step_count.value*s.mm_per_step
    win.positionlabel.configure(text = f'{position:.2f}mm')
    root.after(updatetime, update)

class MainWindow:
    def __init__(self):
        #UI elements:
        self.labelfont = (None, 40) #A tuple to change the text size of the labels
        self.pressurelabel = tk.Label(root, text = "Pressure", bd = 5,
            font = self.labelfont, width = 9)
        self.positionlabel = tk.Label(root, text = "Position", bd = 5,
            font = self.labelfont, width = 9)
        
        self.TidalVolumeLabel = tk.Label(root, text = "Tidal Volume")
        self.TidalVolume = tk.StringVar()
        self.TidalVolume.set("400")
        self.TidalVolumeEntry = tk.Entry(root, textvariable = self.TidalVolume)

        self.RespRateLabel = tk.Label(root, text = "Respiratory Rate")
        self.RespRate = tk.StringVar()
        self.RespRate.set("20")
        self.RespRateEntry = tk.Entry(root, textvariable = self.RespRate)

        self.PressureLimitLabel = tk.Label(root, text = "Pressure Limit")
        self.PressureLimit = tk.StringVar()
        self.PressureLimit.set("40")
        self.PressureLimitEntry = tk.Entry(root, textvariable = self.PressureLimit)

        self.InspFractionLabel = tk.Label(root, text = "Insp. Time Fraction")
        self.InspFraction = tk.StringVar()
        self.InspFraction.set("33")
        self.InspFractionEntry = tk.Entry(root, textvariable = self.InspFraction)

        self.PEEPLabel = tk.Label(root, text = "PEEP")
        self.PEEP = tk.StringVar()
        self.PEEP.set("10")
        self.PEEPEntry = tk.Entry(root, textvariable = self.PEEP)

        self.SetButton = tk.Button(root, text = "Set Changes", command = setvalues)
        self.DiscardButton = tk.Button(root, text = "Discard Changes", command = discardchanges)
        self.CalibrateButton = tk.Button(root, text = "Calibrate",
                                          command = CalibratePressureSensor)
        self.CalibrationValue = tk.StringVar()
        self.CalibrationValue.set("0")
        self.CalibrationEntry = tk.Entry(root, textvariable = self.CalibrationValue)
        
        #putting all the elements in a grid:
        self.pressurelabel.grid(row = 0, column = 0, sticky = 'nesw', columnspan = 2)
        self.positionlabel.grid(row = 1, column = 0, sticky = 'nesw', columnspan = 2)
        self.TidalVolumeLabel.grid(row = 2, column = 0, sticky = 'e')
        self.TidalVolumeEntry.grid(row = 2, column = 1, sticky = 'w')
        self.RespRateLabel.grid(row = 3, column = 0, sticky = 'e')
        self.RespRateEntry.grid(row = 3, column = 1, sticky = 'w')
        self.PressureLimitLabel.grid(row = 4, column = 0, sticky = 'e')
        self.PressureLimitEntry.grid(row = 4, column = 1, sticky = 'w')
        self.InspFractionLabel.grid(row = 5, column = 0, sticky = 'e')
        self.InspFractionEntry.grid(row = 5, column = 1, sticky = 'w')
        self.PEEPLabel.grid(row = 6, column = 0, sticky = 'e')
        self.PEEPEntry.grid(row = 6, column = 1, sticky = 'w')
        self.SetButton.grid(row = 7, column = 0, sticky = 'w')
        self.DiscardButton.grid(row = 7, column = 1, sticky = 'e')
        self.CalibrateButton.grid(row = 8, column = 0, sticky = 'e')
        self.CalibrationEntry.grid(row = 8, column = 1, sticky = 'w')
        
#make an FEwindow in the global namespace. Seems like the easiest way forward
win = MainWindow()

def main():
    measure_process = mp.Process(target = read_sensor_continuous, args = ())
    measure_process.daemon = True #this allows the program to exit without waiting
                        # for the sub-process to end
    measure_process.start()

    motor_process = mp.Process(target = motor_control)
    motor_process.daemon = True
    motor_process.start()
    
    breathe_process = mp.Process(target = breathe_control)
    breathe_process.daemon = True
    breathe_process.start()

    #for reasons I don't understand this callback must be registered here,
    #and not in the motorcontrol function/process. 
    pi.callback(s.motor_step_pin, pigpio.RISING_EDGE, increment_dist)

    #need below for WS control for the FE-machine. Probably don't need it here?
    #root.bind("<KeyPress>", keypress)
    #root.bind("<KeyRelease>", keyrelease)

    update() #first call to update, it will self-scheduel itself going forward
    root.mainloop()
    
if __name__ == '__main__':
    main()
