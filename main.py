import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime, timedelta
import requests
from skyfield.api import load, wgs84, EarthSatellite
import threading
import pytz

class ISSPassPredictor:
    def __init__(self, root):
        self.root = root
        self.root.title("ISS Pass Predictor - Sudbury, Ontario")
        self.root.geometry("1200x700")
        
        # Sudbury coordinates
        self.latitude = 46.5
        self.longitude = -81
        self.location_name = "Sudbury, Ontario"
        self.max_distance_km = 1000
        self.timezone = pytz.timezone('America/Toronto')  # Eastern Time
        
        # TLE data
        self.tle_line1 = None
        self.tle_line2 = None
        self.tle_epoch = None
        
        self.create_widgets()
        
    def create_widgets(self):
        # Header
        header = tk.Label(self.root, text=f"ISS Pass Predictions for {self.location_name}", 
                          font=("Arial", 16, "bold"))
        header.pack(pady=10)
        
        # Info frame
        info_frame = tk.Frame(self.root)
        info_frame.pack(pady=5)
        
        tk.Label(info_frame, text=f"Location: {self.latitude}°N, {self.longitude}°W", 
                 font=("Arial", 10)).pack()
        tk.Label(info_frame, text=f"Maximum Distance: {self.max_distance_km} km", 
                 font=("Arial", 10)).pack()
        
        # Control frame
        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=10)
        
        tk.Label(control_frame, text="Prediction Duration (years):").grid(row=0, column=0, padx=5)
        self.years_var = tk.StringVar(value="0.1")
        years_entry = tk.Entry(control_frame, textvariable=self.years_var, width=10)
        years_entry.grid(row=0, column=1, padx=5)
        
        self.update_btn = tk.Button(control_frame, text="Fetch TLE & Generate Predictions", 
                                    command=self.start_prediction, bg="#4CAF50", fg="white",
                                    font=("Arial", 11, "bold"), padx=10, pady=5)
        self.update_btn.grid(row=0, column=2, padx=10)
        
        self.export_btn = tk.Button(control_frame, text="Export to File", 
                                    command=self.export_to_file, bg="#2196F3", fg="white",
                                    font=("Arial", 11), padx=10, pady=5)
        self.export_btn.grid(row=0, column=3, padx=5)
        
        # Status label
        self.status_label = tk.Label(self.root, text="Ready. Click 'Fetch TLE & Generate Predictions' to start.", 
                                     font=("Arial", 10), fg="blue")
        self.status_label.pack(pady=5)
        
        # TLE info frame
        tle_frame = tk.LabelFrame(self.root, text="TLE Data Info", font=("Arial", 10, "bold"))
        tle_frame.pack(pady=5, padx=10, fill="x")
        
        self.tle_info_label = tk.Label(tle_frame, text="No TLE data loaded yet.", 
                                      font=("Arial", 9), justify="left")
        self.tle_info_label.pack(pady=5, padx=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(pady=5, padx=10, fill="x")
        
        # Results area
        results_frame = tk.LabelFrame(self.root, text="Predicted Passes", font=("Arial", 11, "bold"))
        results_frame.pack(pady=10, padx=10, fill="both", expand=True)
        
        self.results_text = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD, 
                                                      font=("Courier", 9), height=20)
        self.results_text.pack(pady=5, padx=5, fill="both", expand=True)
        
    def fetch_tle(self):
        """Fetch the latest ISS TLE data from CelesTrak"""
        try:
            url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            lines = response.text.strip().split('\n')
            if len(lines) >= 3:
                self.tle_line1 = lines[1].strip()
                self.tle_line2 = lines[2].strip()
                
                # Extract epoch from TLE
                ts = load.timescale()
                satellite = EarthSatellite(self.tle_line1, self.tle_line2, 'ISS', ts)
                self.tle_epoch = satellite.epoch.utc_datetime()
                
                return True
            else:
                return False
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch TLE data: {str(e)}")
            return False
    
    def estimate_accuracy(self, days_from_epoch):
        """
        Estimate prediction accuracy based on days from TLE epoch.
        Returns estimated error in kilometers and reliability string.
        """
        if days_from_epoch <= 3:
            error = 1 + (days_from_epoch / 3) * 4  # 1-5 km
            reliability = "EXCELLENT"
        elif days_from_epoch <= 7:
            error = 5 + ((days_from_epoch - 3) / 4) * 15  # 5-20 km
            reliability = "VERY GOOD"
        elif days_from_epoch <= 30:
            error = 20 + ((days_from_epoch - 7) / 23) * 80  # 20-100 km
            reliability = "GOOD"
        elif days_from_epoch <= 90:
            error = 100 + ((days_from_epoch - 30) / 60) * 400  # 100-500 km
            reliability = "MODERATE"
        elif days_from_epoch <= 180:
            error = 500 + ((days_from_epoch - 90) / 90) * 500  # 500-1000 km
            reliability = "POOR"
        else:
            # Exponential degradation beyond 180 days
            error = 1000 * (1 + (days_from_epoch - 180) / 180)
            reliability = "VERY POOR"
        
        return error, reliability
    
    def calculate_passes(self, years):
        """
        Calculate ISS passes using a Coarse (1-min) then Fine (1-sec) search strategy.
        Uses true slant-range distance via Skyfield's altaz() method.
        """
        ts = load.timescale()
        satellite = EarthSatellite(self.tle_line1, self.tle_line2, 'ISS', ts)
        location = wgs84.latlon(self.latitude, self.longitude)
        
        # Time range
        start_time = ts.now()
        end_time = ts.utc(start_time.utc_datetime() + timedelta(days=365*years))
        
        passes = []
        
        # PHASE 1: COARSE SEARCH - Check every 1 minute to find pass windows
        current = start_time
        step = timedelta(minutes=1)
        
        window_start = None
        in_window = False
        
        end_dt = end_time.utc_datetime()
        
        while current.utc_datetime() < end_dt:
            # Calculate geometric position relative to Sudbury
            difference = satellite.at(current) - location.at(current)
            alt, az, distance = difference.altaz()
            
            # Use true straight-line distance (slant range) in km
            dist_km = distance.km
            
            # Check if within range
            if dist_km <= self.max_distance_km:
                if not in_window:
                    in_window = True
                    window_start = current
            else:
                if in_window:
                    # Pass window just ended in coarse scan
                    window_end = current
                    
                    # PHASE 2: FINE SEARCH - Zoom in with 1-second precision
                    precise_pass = self.refine_pass_data(
                        satellite, location, window_start, window_end, ts
                    )
                    
                    if precise_pass:
                        passes.append(precise_pass)
                    
                    in_window = False
            
            # Move forward 1 minute
            current = ts.utc(current.utc_datetime() + step)
            
        return passes

    def refine_pass_data(self, satellite, location, start_time, end_time, ts):
        """
        Phase 2: Scans an identified time window second-by-second 
        to find exact pass details with high precision using vectorization.
        """
        # Add buffer to ensure we catch the true edges
        t0 = start_time.utc_datetime() - timedelta(minutes=1)
        t1 = end_time.utc_datetime() + timedelta(minutes=1)
        
        # Create time array with 1-second steps
        duration_seconds = int((t1 - t0).total_seconds())
        
        # Build list of datetime objects at 1-second intervals
        times_list = []
        curr_t = t0
        for _ in range(duration_seconds):
            times_list.append(curr_t)
            curr_t += timedelta(seconds=1)
        
        # Convert to Skyfield times (vectorized - all at once)
        times = ts.from_datetimes(times_list)
        
        # Vectorized calculation - computes all positions simultaneously
        difference = satellite.at(times) - location.at(times)
        alts, azs, distances = difference.altaz()
        
        # Find index of minimum distance (closest approach)
        dist_km_list = distances.km
        min_dist_index = dist_km_list.argmin()
        
        min_distance = dist_km_list[min_dist_index]
        
        # If closest approach is still too far, ignore this pass
        if min_distance > self.max_distance_km:
            return None
        
        # Get maximum altitude during pass
        max_alt = alts.degrees.max()
        
        # Get exact time of closest approach
        closest_t = times[min_dist_index]
        
        # Calculate actual duration: count seconds where ISS is within range
        duration_sec = sum(d <= self.max_distance_km for d in dist_km_list)
        duration_mins = duration_sec / 60.0

        # Calculate accuracy estimation
        days_from_epoch = (closest_t.utc_datetime() - self.tle_epoch).total_seconds() / 86400
        error_km, reliability = self.estimate_accuracy(days_from_epoch)
        
        return {
            'start': start_time.utc_datetime(),
            'end': end_time.utc_datetime(),
            'closest_time': closest_t.utc_datetime(),
            'min_distance': min_distance,
            'max_altitude': max_alt,
            'duration': duration_mins,
            'error_km': error_km,
            'reliability': reliability
        }
    
    def format_datetime_et(self, dt_utc):
        """Convert UTC datetime to Eastern Time with 12-hour format, handling DST"""
        # Convert UTC to Eastern Time (automatically handles DST)
        dt_et = dt_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        
        # Format in 12-hour time
        time_str = dt_et.strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Get timezone abbreviation (EST or EDT)
        tz_abbr = dt_et.strftime('%Z')
        
        return f"{time_str} {tz_abbr}"
    
    def format_results(self, passes):
        """Format the prediction results for display"""
        output = []
        output.append("=" * 140)
        output.append(f"ISS PASS PREDICTIONS FOR {self.location_name.upper()}")
        
        # Convert current time to ET
        now_et = datetime.now(pytz.UTC).astimezone(self.timezone)
        output.append(f"Generated: {now_et.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
        
        # Convert TLE epoch to ET
        tle_epoch_et = self.tle_epoch.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        output.append(f"TLE Epoch: {tle_epoch_et.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
        
        output.append(f"Total Passes Found: {len(passes)}")
        output.append("=" * 140)
        output.append("")
        output.append(f"{'Pass #':<8} {'Date/Time (Eastern Time)':<30} {'Distance':<12} {'Max Alt':<10} {'Duration':<10} {'Est. Error':<15} {'Reliability':<15}")
        output.append(f"{'':8} {'Closest Approach':<30} {'(km)':<12} {'(degrees)':<10} {'(min)':<10} {'(km)':<15} {'':<15}")
        output.append("-" * 140)
        
        for i, p in enumerate(passes, 1):
            date_str = self.format_datetime_et(p['closest_time'])
            dist_str = f"{p['min_distance']:.2f}"
            alt_str = f"{p['max_altitude']:.2f}"
            dur_str = f"{p['duration']:.2f}"
            error_str = f"±{p['error_km']:.0f}"
            
            output.append(f"{i:<8} {date_str:<30} {dist_str:<12} {alt_str:<10} {dur_str:<10} {error_str:<15} {p['reliability']:<15}")
        
        output.append("=" * 140)
        output.append("")
        output.append("CALCULATION METHODOLOGY:")
        output.append("- Phase 1: Coarse scan using 1-minute steps to identify pass windows")
        output.append("- Phase 2: Fine vectorized scan using 1-second steps within each window")
        output.append("- Distance: True 3D slant range using Skyfield's altaz() method (NASA-grade spherical geometry)")
        output.append("- Precision: Closest approach accurate to within ~7.66 km (ISS orbital speed × 1 second)")
        output.append("- Duration: Actual seconds the ISS is within range (not just start-to-end approximation)")
        output.append("- Performance: Vectorized calculations process entire pass windows simultaneously")
        output.append("")
        output.append("TIME ZONE NOTES:")
        output.append("- All times are shown in Eastern Time (America/Toronto timezone)")
        output.append("- Daylight Saving Time (EDT) is automatically applied when applicable (March-November)")
        output.append("- Standard Time (EST) is used during winter months (November-March)")
        output.append("")
        output.append("ACCURACY NOTES:")
        output.append("- EXCELLENT (Days 0-3): ±1-5 km - Highly accurate")
        output.append("- VERY GOOD (Days 3-7): ±5-20 km - Very reliable")
        output.append("- GOOD (Days 7-30): ±20-100 km - Generally reliable")
        output.append("- MODERATE (Days 30-90): ±100-500 km - Use with caution")
        output.append("- POOR (Days 90-180): ±500-1000 km - Low confidence")
        output.append("- VERY POOR (Days 180+): ±1000+ km - Unreliable, for reference only")
        output.append("")
        output.append("NOTE: Predictions degrade due to atmospheric drag, orbital maneuvers, and space weather.")
        output.append("For best accuracy, update TLE data regularly and regenerate predictions.")
        
        return "\n".join(output)
    
    def start_prediction(self):
        """Start the prediction process in a separate thread"""
        try:
            years = float(self.years_var.get())
            if years <= 0 or years > 10:
                messagebox.showerror("Error", "Please enter a value between 0 and 10 years.")
                return
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number of years.")
            return
        
        self.update_btn.config(state="disabled")
        self.progress.start()
        
        thread = threading.Thread(target=self.run_prediction, args=(years,))
        thread.daemon = True
        thread.start()
    
    def run_prediction(self, years):
        """Run the prediction calculation"""
        self.status_label.config(text="Fetching latest TLE data from CelesTrak...")
        
        if not self.fetch_tle():
            self.progress.stop()
            self.update_btn.config(state="normal")
            self.status_label.config(text="Failed to fetch TLE data.", fg="red")
            return
        
        # Update TLE info
        tle_epoch_et = self.tle_epoch.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
        tle_info = f"TLE Epoch: {tle_epoch_et.strftime('%Y-%m-%d %I:%M:%S %p %Z')}\n"
        tle_info += f"Line 1: {self.tle_line1}\n"
        tle_info += f"Line 2: {self.tle_line2}"
        self.tle_info_label.config(text=tle_info)
        
        self.status_label.config(text=f"Calculating passes for {years} year(s)... This may take a few minutes.")
        
        passes = self.calculate_passes(years)
        
        self.status_label.config(text=f"Formatting results... Found {len(passes)} passes.")
        
        results = self.format_results(passes)
        
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(1.0, results)
        
        self.progress.stop()
        self.update_btn.config(state="normal")
        self.status_label.config(text=f"Complete! Found {len(passes)} passes over {years} year(s).", fg="green")
        
        # Store results for export
        self.last_results = results
    
    def export_to_file(self):
        """Export results to a text file"""
        if not hasattr(self, 'last_results'):
            messagebox.showwarning("Warning", "No results to export. Please generate predictions first.")
            return
        
        filename = f"ISS_Passes_Sudbury_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(filename, 'w') as f:
                f.write(self.last_results)
            messagebox.showinfo("Success", f"Results exported to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export file: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = ISSPassPredictor(root)
    root.mainloop()