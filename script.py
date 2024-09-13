import os
import time
import pyautogui
from PIL import Image, ImageFilter
import tkinter as tk
from tkinter import messagebox, IntVar
import threading
import sys
from pynput import mouse, keyboard
import numpy as np
import boto3
import msvcrt
from io import BytesIO
import queue
import socket

class ActivityTracker:
    def __init__(self):
        self.activity_interval = 5  # in seconds
        self.screenshot_interval = 5  # in minutes
        self.capture_screenshots = True
        self.capture_blurred = False
        self.capturing = False
        self.aws_bucket_name = 'dummyvinove'
        self.aws_region = 'us-east-1'
        self.offline_queue = queue.Queue()
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        self.mouse_positions = []
        self.key_presses = []
        self.last_activity_time = time.time()

    def upload_to_s3(self, filename, data, is_log=False):
        key = f"logs/{filename}" if is_log else f"screenshots/{filename}"
        try:
            if is_log:
                self.s3_client.put_object(Body=data.getvalue(), Bucket=self.aws_bucket_name, Key=key)
            else:
                self.s3_client.upload_fileobj(data, self.aws_bucket_name, key)
            print(f"Uploaded {key} successfully.")
        except Exception as e:
            print(f"Error uploading {key}: {e}")
            self.offline_queue.put((filename, data, is_log))

    def process_offline_queue(self):
        while not self.offline_queue.empty():
            filename, data, is_log = self.offline_queue.get()
            try:
                self.upload_to_s3(filename, data, is_log)
            except Exception as e:
                print(f"Retry failed for {filename}: {e}")
                self.offline_queue.put((filename, data, is_log))
                break

    @staticmethod
    def is_connected():
        try:
            socket.create_connection(("8.8.8.8", 53))
            return True
        except OSError:
            return False

    def capture_and_upload_screenshot(self):
        if not self.capture_screenshots:
            return
        screenshot = pyautogui.screenshot()
        if self.capture_blurred:
            screenshot = screenshot.filter(ImageFilter.GaussianBlur(10))
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f'screenshot_{timestamp}.png'

        img_byte_arr = BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        if self.is_connected():
            self.upload_to_s3(filename, img_byte_arr, is_log=False)
        else:
            print("No internet connection. Screenshot added to the queue.")
            self.offline_queue.put((filename, img_byte_arr, False))

    def log_activity(self):
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f'activity_log_{timestamp}.txt'
        log_content = f"Mouse movements: {self.mouse_positions}\nKey presses: {self.key_presses}\n"

        log_data = BytesIO(log_content.encode())
        log_data.seek(0)

        if self.is_connected():
            self.upload_to_s3(filename, log_data, is_log=True)
        else:
            print("No internet connection. Log added to the queue.")
            self.offline_queue.put((filename, log_data, True))

        self.mouse_positions = []
        self.key_presses = []
        self.last_activity_time = time.time()

    def is_irregular_activity(self):
        if len(self.mouse_positions) < 2:
            return False
        
        diffs = np.diff(self.mouse_positions, axis=0)
        if np.all(diffs == diffs[0]):  
            return True
        
        if len(self.key_presses) > 20:
            avg_time_between_presses = np.mean(np.diff(self.key_presses))
            if avg_time_between_presses < 0.05:
                return True
        
        return False

    def on_move(self, x, y):
        self.mouse_positions.append((x, y))

    def on_press(self, key):
        self.key_presses.append(time.time())

    def activity_monitoring_task(self):
        mouse_listener = mouse.Listener(on_move=self.on_move)
        keyboard_listener = keyboard.Listener(on_press=self.on_press)
        mouse_listener.start()
        keyboard_listener.start()

        while self.capturing:
            time.sleep(self.activity_interval)
            if time.time() - self.last_activity_time >= self.activity_interval:
                if not self.is_irregular_activity():
                    self.log_activity()
                else:
                    print("Irregular activity detected. Discarding this interval.")
            self.process_offline_queue()

        mouse_listener.stop()
        keyboard_listener.stop()

    def screenshot_task(self):
        while self.capturing:
            self.capture_and_upload_screenshot()
            self.process_offline_queue()
            time.sleep(self.screenshot_interval * 60)

    def start_capturing(self):
        if not self.capturing:
            self.capturing = True
            threading.Thread(target=self.activity_monitoring_task, daemon=True).start()
            if self.capture_screenshots:
                threading.Thread(target=self.screenshot_task, daemon=True).start()
            messagebox.showinfo("Status", "Activity tracking started.")

    def stop_capturing(self):
        self.capturing = False
        messagebox.showinfo("Status", "Activity tracking stopped.")

    def set_activity_interval(self, value):
        self.activity_interval = int(value)
        print(f"Activity logging interval set to: {self.activity_interval} seconds")

    def set_screenshot_interval(self, value):
        self.screenshot_interval = int(value)
        print(f"Screenshot interval set to: {self.screenshot_interval} minutes")

    def toggle_screenshot_capture(self):
        self.capture_screenshots = not self.capture_screenshots
        state = "Enabled" if self.capture_screenshots else "Disabled"
        print(f"Screenshot capture: {state}")

    def toggle_blur(self):
        self.capture_blurred = not self.capture_blurred
        state = "Blurred" if self.capture_blurred else "Clear"
        print(f"Screenshots will be: {state}")

class Application:
    def __init__(self, master):
        self.master = master
        self.tracker = ActivityTracker()
        self.create_widgets()

    def create_widgets(self):
        tk.Button(self.master, text="Start Tracking", command=self.tracker.start_capturing).grid(row=0, column=0, padx=10, pady=10)
        tk.Button(self.master, text="Stop Tracking", command=self.tracker.stop_capturing).grid(row=0, column=1, padx=10, pady=10)

        tk.Label(self.master, text="Activity Logging Interval (seconds):").grid(row=1, column=0, padx=10, pady=10)
        activity_slider = tk.Scale(self.master, from_=1, to=60, orient='horizontal', command=self.tracker.set_activity_interval)
        activity_slider.set(self.tracker.activity_interval)
        activity_slider.grid(row=1, column=1, padx=10, pady=10)

        tk.Label(self.master, text="Screenshot Interval (minutes):").grid(row=2, column=0, padx=10, pady=10)
        screenshot_slider = tk.Scale(self.master, from_=1, to=60, orient='horizontal', command=self.tracker.set_screenshot_interval)
        screenshot_slider.set(self.tracker.screenshot_interval)
        screenshot_slider.grid(row=2, column=1, padx=10, pady=10)

        screenshot_var = IntVar()
        tk.Checkbutton(self.master, text="Capture Screenshots", variable=screenshot_var, command=self.tracker.toggle_screenshot_capture).grid(row=3, column=0, padx=10, pady=10)

        blur_var = IntVar()
        tk.Checkbutton(self.master, text="Blur Screenshots", variable=blur_var, command=self.tracker.toggle_blur).grid(row=3, column=1, padx=10, pady=10)

def check_single_instance():
    lock_file = 'my_app.lock'
    lock_file_obj = open(lock_file, 'w')
    try:
        msvcrt.locking(lock_file_obj.fileno(), msvcrt.LK_NBLCK, 1)
    except IOError:
        messagebox.showerror("Error", "Another instance of the application is already running.")
        sys.exit()

if __name__ == "__main__":
    check_single_instance()
    root = tk.Tk()
    root.title("Activity Tracking Agent")
    app = Application(root)
    root.mainloop()