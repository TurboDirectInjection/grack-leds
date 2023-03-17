# Example using PIO to drive a set of WS2812 LEDs.

import array, time
from machine import Pin, Timer
import rp2
from math import floor
import random
import _thread
from ulab import numpy as np


NUM_PLAYERS  = 6
STOP_LOOPING_EFFECT = False # Global variable allowing looping effects to be interrupted

# Configure the number of WS2812 LEDs.
NUM_LEDS = 200
PIN_NUM = 1 # pinout pin = PIN_NUM + 1; indexing starts at zero because why not
brightness = 0.1 # Scalar from 0-1
LED_IDXS = range(0, NUM_LEDS) # Array of 

# Some color lookups
BLACK = (0, 0, 0)
RED = (255, 0, 0)
YELLOW = (255, 150, 0)
GREEN = (0, 255, 0)
CYAN = (0, 255, 255)
BLUE = (0, 0, 255)
PURPLE = (180, 0, 255)
WHITE = (255, 255, 255)
COLORS = (BLACK, RED, YELLOW, GREEN, CYAN, BLUE, PURPLE, WHITE)

######################## PIO STATE MACHINE ################################
rp2.PIO(0).remove_program() # Clears PIO memory for pico-W compatibility
# Assembly instructions that dictate the hardware-level procedure for writing data to LEDs
@rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW, out_shiftdir=rp2.PIO.SHIFT_LEFT, autopull=True, pull_thresh=24)
def ws2812():
    T1 = 2
    T2 = 5
    T3 = 3
    wrap_target()
    label("bitloop")
    out(x, 1)               .side(0)    [T3 - 1]
    jmp(not_x, "do_zero")   .side(1)    [T1 - 1]
    jmp("bitloop")          .side(1)    [T2 - 1]
    label("do_zero")
    nop()                   .side(0)    [T2 - 1]
    wrap()


# Create the StateMachine with the ws2812 program, outputting on pin
sm = rp2.StateMachine(0, ws2812, freq=8_000_000, sideset_base=Pin(PIN_NUM))

# Start the StateMachine, it will wait for data on its FIFO.
sm.active(1)

# Display a pattern on the LEDs via an array of LED RGB values.
ar = array.array("I", [0 for _ in range(NUM_LEDS)])

########################## PIXEL FUNCTIONS #############################
def pixels_show():
    dimmer_ar = array.array("I", [0 for _ in range(NUM_LEDS)])
    for i,c in enumerate(ar):
        r = int(((c >> 8) & 0xFF) * brightness)
        g = int(((c >> 16) & 0xFF) * brightness)
        b = int((c & 0xFF) * brightness)
        dimmer_ar[i] = (g<<16) + (r<<8) + b
    sm.put(dimmer_ar, 8)
    time.sleep_ms(10)

def tuple2bits(color):
    return (color[1]<<16) + (color[0]<<8) + color[2]
    
def pixels_set(i, color):
    ar[i] = (color[1]<<16) + (color[0]<<8) + color[2]


###################### PLAYER TURN INDICATOR ######################
padding = 10   # Number of LEDs gap between players
player_bin_width = NUM_LEDS // NUM_PLAYERS # Divides LED string into integer-valued player-sized bins
if padding > player_bin_width: # Check to make sure no negative indexing
    player_light_width = 0
else:
    player_light_width = player_bin_width - padding
player_posns = [(0, 0) for _ in range(NUM_PLAYERS)] # This is an array of tuples containing start and stop indices for each player's location
for i in range(NUM_PLAYERS):
    offset = player_bin_width * i
    player_posns[i] = (offset + padding, offset + padding + player_light_width) # Is it centered? No. Just rotate the LED string and be done.
    

########################## FIRE EFFECTS #############################
# @param temp = [0, 255] integer value, larger = hotter.
#  Should be a rough approximation of blackbody radiation in
#  visible spectrum, if you scale/shift the temperatures
def fire_tone(temp):
    if temp < 0 or temp > 255:
        return (0, 0, 0)
    if temp < 85: # Low temperatures are just dim red
        return (temp * 3, 0, 0)
    if temp < 170: # Medium temperatures shift from red to yellow
        return (255, (temp - 85), 0)
    else: # High temperatures shift towards white
        return (255, (temp - 85), (temp - 170))

# Just sweeps through the fire tone colors.
def fire_sweep():
    for j in range(255):
        for i in range(NUM_LEDS):
            temp = (i * 256 // NUM_LEDS) + j
            pixels_set(i, fire_tone(temp & 255))
        pixels_show()
        time.sleep(0.01)

def fire_callback(t):
    global STOP_LOOPING_EFFECT
    STOP_LOOPING_EFFECT = True
    
# @param duration: time in ms for fire storm to run
def fire_storm(duration):
    global STOP_LOOPING_EFFECT # Lets exterior programs communicate a stop
    # Create timer to trigger end of fire_storm
    timer = machine.Timer(mode=Timer.ONE_SHOT, callback=fire_callback, period=duration)
    
    spark_chance = 0.99 # Likelihood of igniting new hotspot (0-1, 1 being no sparks)
    cooldown = 0.98 # How much heat to subtract from everything
    maxheat = 200
    minheat = 20
    
    heatvals = [random.randint(0, 255) for _ in range(NUM_LEDS)] # Initial seed values for fire heat
    newheat  = [0 for _ in range(NUM_LEDS)]
    while not STOP_LOOPING_EFFECT:
        sparks = [random.random() > spark_chance for _ in range(NUM_LEDS)] # Where to ignite new flame
        
        for i in range(NUM_LEDS):
            '''
            if idx < 1: # Handle wraparound conditions
                prev_idx = NUM_LEDS - 1
            else:
                prev_idx = idx - 1
            if idx >= NUM_LEDS - 1:
                next_idx = 0
            else:
                next_idx = idx + 1
            '''
            prev_idx1 = (i - 1) % NUM_LEDS
            prev_idx2 = (i - 2) % NUM_LEDS
            next_idx1 = (i + 1) % NUM_LEDS
            next_idx2 = (i + 2) % NUM_LEDS

                
            newheat[i] = (heatvals[i] * 3 + heatvals[prev_idx1] * 2 + heatvals[prev_idx2] + heatvals[next_idx1] * 2 + heatvals[next_idx2]) // 9 # Heat diffuses to neighbors and decreases
            if sparks[i] and newheat[i] < 128: # Is this a site for new heat?
                newheat[i] = newheat[i] + random.randint(128, 255 - newheat[i])
            newheat[i] = min(maxheat, int(newheat[i] * cooldown))
            newheat[i] = max(minheat, newheat[i])
            pixels_set(i, fire_tone(newheat[i]))
        pixels_show()
        heatvals = newheat
    
        
    STOP_LOOPING_EFFECT = False

def disp_player(player_num):
    '''
    (start_idx, stop_idx) = player_posns[player_num]
    ar = [tuple2bits(RED) if ((i >= start_idx) and (i <= stop_idx)) else tuple2bits(BLACK) for i in LED_IDXS]
    pixels_show()
    '''
    for i in range(NUM_LEDS):
        if (i >= player_posns[player_num][0]) and (i <= player_posns[player_num][1]):
            pixels_set(i, RED)
        else:
            pixels_set(i, BLACK)
    
    pixels_show()
    


fire_storm(100000)
#fire_sweep()
