import pyautogui
import time

print("Du har 5 sekunder på å gjøre BetSolid-vinduet aktivt...")
time.sleep(5)

img = pyautogui.screenshot(
    region=(1420, 380, 220, 140)
)

img.save("hero_cards_debug.png")

print("Lagret hero_cards_debug.png")