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

#physics:
cmH2OperHPa = 1.02 #1 HPa corresponds to 1.02 centimeters of water
#pin list:
MotorStepPin = 12
MotorDirPin = 16
MotorResetPin = 7
MotorSleepPin = 20
SolenoidPin = 26
mosi = 0
sensor1pin = digitalio.DigitalInOut(board.D5)
sensor2pin = digitalio.DigitalInOut(board.D6)

StepsPerTurn = 200 #200 or 400 generally, depends on stepper motor
GearReduction = 5+ 2/11 #for stepper motors with attached gearbox
NumberOfTeeth = 15 #Number of teeth on the pinion driving the rack
Module = 2 #Is a property of the rack and pinion system
PitchDiameter = Module*NumberOfTeeth #I got a youtube video about this!
mmPerStep = math.pi*PitchDiameter/(StepsPerTurn*GearReduction)
cylinderradius = 34.1 #mm

refreshrate = 30 #how many times per second to update UI
updatetime = math.floor(1000/refreshrate) #1/refreshrate, *1000 for milliseconds

#objects and modes setup:
pi = pigpio.pi()
root = tk.Tk()
root.tk.call('tk', 'scaling', 2.0)
spi = busio.SPI(board.SCK, MOSI = board.MOSI, MISO = board.MISO)
PressureSensorAmbient = adafruit_bme280.Adafruit_BME280_SPI(spi, sensor1pin)
PressureSensorAmbient.mode = adafruit_bme280.MODE_NORMAL
PressureSensorAmbient.standby_period = adafruit_bme280.STANDBY_TC_10
PressureSensorPatient = adafruit_bme280.Adafruit_BME280_SPI(spi, sensor2pin)
PressureSensorPatient.mode = adafruit_bme280.MODE_NORMAL
PressureSensorPatient.standby_period = adafruit_bme280.STANDBY_TC_10

#setting up some of the pins:
pi.set_mode(MotorStepPin, pigpio.OUTPUT)
pi.set_mode(MotorDirPin, pigpio.OUTPUT)
pi.set_mode(MotorSleepPin, pigpio.OUTPUT)
pi.set_mode(MotorResetPin, pigpio.OUTPUT)

#setting up some multiprocessing shared variables
laststepcount = mp.Value('i', 0) #incremental position in stepper motor steps
movedirection = mp.Value('i', 0) #in what direction the stepper is moving
lastgaugepressure = mp.Value('f', 0) #Difference between outside and inside, corrected for sensor error
lastgaugepressureraw = mp.Value('f', 0) #Difference between ouside and inside before correction
lastpatientpressure = mp.Value('f', 0) #absolute pressure patient side
lastambientpressure = mp.Value('f', 0) #absolute ambient pressure
pressureoffset = mp.Value('f', 0) #difference in reading between the 2 sensors
                                #when the actual difference is 0
targetdistance = mp.Value('f', 0)
targetsteps = mp.Value('i', 0)
PEEP = mp.Value('f', 0)

#measure sensor values for a while to figure out what the offset between the
#two is
def CallibratePressureSensor():
    start = time.time()
    pressurevalues = []
    while time.time() - start < 5:
        pressurevalues.append(lastgaugepressureraw.value)
        time.sleep(0.02)
    #print(pressurevalues)
    pressureoffset.value = sum(pressurevalues)/len(pressurevalues)
    win.CallibrationValue.set(pressureoffset.value)

#Take values from UI and actually insert and use them
def setvalues():
    pass

#Take current set values and insert them into UI, discarding changes made
def discardchanges():
    pass


def incrementdist(gpio, level, tick):
    timestamp = time.time()
    if movedirection.value == 0:
        laststepcount.value -= 1
    else:
        laststepcount.value += 1

#one process to continually measure the pressure
def read_sensor_continuous():
    while True:
        timestamp = time.time()
        AmbientPressure = PressureSensorAmbient.pressure
        PatientPressure = PressureSensorPatient.pressure
        PressureDifference = PatientPressure - AmbientPressure
        GaugePressure = PressureDifference - pressureoffset.value
        lastambientpressure.value = AmbientPressure
        lastpatientpressure.value = PatientPressure
        lastgaugepressureraw.value = PressureDifference
        lastgaugepressure.value = GaugePressure
        time.sleep(0.01)

#one process to control the motor
def motorcontrol():
    currentstepspersecond = 0
    currentdirection = 0 #0 for backwards, 1 for fowards (air into patient)
    maxstepspersecond = 5000
    updatetime = 0.01
    accelerationsteptime = updatetime
    speedincreaseperstep = 100 #steps/s to add per updatetime
    acceleration = speedincreaseperstep/accelerationsteptime #in steps/s/s
    maxdecel = 2*acceleration
    totalaccelerationsteps = maxstepspersecond
    acceptablestepserror = 5

    pi.write(MotorSleepPin, True)
    pi.write(MotorResetPin, True)
    while True:
        stepstogo = targetsteps.value - laststepcount.value #can be + or -
        #first check we're going in the right direction to begin with.
        if stepstogo > 0 and currentdirection == 0 or \
            stepstogo < 0 and currentdirection == 1: #slow down and reverse
            #print("reversing 0 to 1")
            currentstepspersecond -= speedincreaseperstep
            if currentstepspersecond < 0:
                currentstepspersecond = 0
                if currentdirection == 0:
                    currentdirection = 1
                else:
                    currentdirection = 0
##        elif stepstogo < 0 and currentdirection == 1:
##            print("reversing 1 to 0")
##            currentstepspersecond -= speedincreaseperstep
##            if currentstepspersecond < 0:
##                currentstepspersecond = 0
##                currentdirection = 0
        else: #if we are going in the right direction
            decelticks = accelerationsteptime*(currentstepspersecond/speedincreaseperstep)
            deceldist = 0.5*currentstepspersecond**2/acceleration #how much further do we go if we brake now
            if deceldist >= abs(stepstogo): #time to slow down
                
                if stepstogo == 0:
                    deceleration = maxdecel
                else:
                    deceleration = abs(0.5*currentstepspersecond**2/stepstogo)
                if deceleration > maxdecel:
                    deceleration = maxdecel
                #print("decelerating", deceldist, currentstepspersecond, stepstogo, deceleration)
                currentstepspersecond -= int(deceleration*accelerationsteptime)
                if currentstepspersecond < 0:
                    currentstepspersecond = 0
                    if currentdirection == 0:
                        currentdirection = 1
                    else:
                        currentdirection = 0
            #if we're too far off the target, and we shouldn't slow down yet, speed up
            elif abs(stepstogo) > acceptablestepserror:
                #print("accelerating", currentstepspersecond, stepstogo)
                currentstepspersecond += speedincreaseperstep
                if currentstepspersecond > maxstepspersecond:
                    currentstepspersecond = maxstepspersecond
        #print(currentdirection, currentstepspersecond)
        movedirection.value = currentdirection
        pi.write(MotorDirPin, currentdirection)
        pi.hardware_PWM(MotorStepPin, currentstepspersecond, 500000)
        time.sleep(updatetime)
            
        
#one process to control the breathing rhythem
def breathecontrol():
    while True:
        PEEP.value = 5
        targetdistance.value = 150
        targetsteps.value = int(targetdistance.value/mmPerStep)
        print("Inspiring")
        time.sleep(1)
        print("Exhaling")
        targetdistance.value = 0
        targetsteps.value = 0
        expirationstart = time.time()
        if lastgaugepressure.value > PEEP.value:
            print("Waiting for pressure to drop to PEEP", lastgaugepressure.value, PEEP.value)
            pi.write(SolenoidPin, True)
            print("Solenoid open", time.time())
            while lastgaugepressure.value > PEEP.value and \
                  time.time() - expirationstart < 2:
                time.sleep(0.001)
        
        print("Closing Solenoid", time.time())
        pi.write(SolenoidPin, False)
        while time.time() - expirationstart < 2:
            time.sleep(0.001)
        #time.sleep(0.001)        
##        #wait for trigger, either from pressure or time
##        #record time, push piston, monitor pressure
##        now = time.time()
##        movedirection.value = 1
##        pi.write(MotorDirPin, movedirection.value)
##        pi.hardware_PWM(MotorStepPin, 500, 500000)
##        time.sleep(0.5)
##        pi.hardware_PWM(MotorStepPin, 0, 500000)
##        time.sleep(0.5)
##        movedirection.value = 0
##        pi.write(MotorDirPin, movedirection.value)
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
    pressure = lastgaugepressure.value*cmH2OperHPa
    win.pressurelabel.configure(text = f'{pressure:.1f}cm')
    position = laststepcount.value*mmPerStep
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
        self.CallibrateButton = tk.Button(root, text = "Callibrate",
                                          command = CallibratePressureSensor)
        self.CallibrationValue = tk.StringVar()
        self.CallibrationValue.set("0")
        self.CallibrationEntry = tk.Entry(root, textvariable = self.CallibrationValue)
        
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
        self.CallibrateButton.grid(row = 8, column = 0, sticky = 'e')
        self.CallibrationEntry.grid(row = 8, column = 1, sticky = 'w')
        
#make an FEwindow in the global namespace. Seems like the easiest way forward
win = MainWindow()

def main():
    measureprocess = mp.Process(target = read_sensor_continuous, args = ())
    measureprocess.daemon = True #this allows the program to exit without waiting
                        # for the sub-process to end
    measureprocess.start()

    motorprocess = mp.Process(target = motorcontrol)
    motorprocess.daemon = True
    motorprocess.start()
    
    breatheprocess = mp.Process(target = breathecontrol)
    breatheprocess.daemon = True
    breatheprocess.start()

    #for reasons I don't understand this callback must be registered here,
    #and not in the motorcontrol function/process. 
    pi.callback(MotorStepPin, pigpio.RISING_EDGE, incrementdist)

    #need below for WS control for the FE-machine. Probably don't need it here?
    #root.bind("<KeyPress>", keypress)
    #root.bind("<KeyRelease>", keyrelease)

    update() #first call to update, it will self-scheduel itself going forward
    root.mainloop()
    
if __name__ == '__main__':
    main()
