from flask import Flask, request, jsonify
from supabase import create_client
from supabase.lib.client_options import ClientOptions
from flask_cors import CORS
from dotenv import load_dotenv
import hashlib
import os
import secrets
import json
from datetime import datetime, timezone

load_dotenv()

# Supabase connection setup
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(
    url,
    key,
    options=ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
    )
)

admin = supabase.auth.admin

#secret key generator
secret_key = secrets.token_hex(32)

app = Flask(__name__)
# Allow multiple origins
CORS(app, resources={r"/*": {"origins": ["https://facialrecog-2b424.web.app", "http://localhost:5173"]}}, supports_credentials=True)
CORS(app)
app.secret_key = secret_key

#Hash Function
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

#Time Stamp
timestamp = datetime.now().isoformat()

""""
GUEST FUNCTIONS
"""
#Registration Function
@app.route("/register", methods=["POST"])
def register():
    try:
        # Get the data from the frontend
        data = request.get_json()
        
        try:
            #Filling in variables
            first_name = data.get("firstName")
            last_name = data.get("lastName")
            mobile_number = data.get("phoneNum")
            email = data.get("email")
            password_hash = hash_password(data.get("password"))
            facialID_consent = False
        except Exception as e:
            print("Error occured: ", e)
        
        # Check if email already exists in the guest table
        existing_guest = supabase.table('guest').select('*').eq('email', email).execute()
        if existing_guest.data:
            return jsonify({'success': False, 'message': 'Email already registered.'}), 400

        # Create user in Supabase Authentication
        try:
            auth_response = supabase.auth.sign_up({
                "email": email,
                "password": data.get("password"),
                "options": {"data": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "mobile_number": mobile_number
                }}
            })
            user_id = auth_response.user.id

            print("Successfully signed up")
        except Exception as e:
            print("Error during authentication signup:", e)
            return jsonify({"success": False, "message": "Error creating user in authentication."}), 400
        
        # No facial opt in
        try:
            #Inserting into guest table
            guest_response = supabase.table("guest").insert(
                {   
                    "user_id": user_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "mobile_number": mobile_number,
                    "password_hash": password_hash,
                    "facialid_consent": facialID_consent
                }
            ).execute()

            try:
                profile_response = supabase.table("profiles").insert({
                    "id": user_id,
                    "role": "guest"
                }).execute()
            except Exception as e:
                print(e)

            print("Profile Table respones:", profile_response)

            # Check response after insertion
            if guest_response.data and profile_response.data:
                return jsonify({"success": True, "message": "Registration successful!"}), 200
            else:
                supabase.table("guest").delete().eq("user_id", user_id).execute()
                supabase.table("profiles").delete().eq("id", user_id).execute()
                return jsonify({"success": False, "message": "Error inserting into tables."}), 400
   
        except Exception as e:
                supabase.table("guest").delete().eq("user_id", user_id).execute()
                supabase.table("profiles").delete().eq("id", user_id).execute()
                return jsonify({"success": False, "message": "Error inserting into tables."}), 400
        
    except Exception as e:
        print("Error:", e)
        return jsonify({"success": False, "message": str(e)}), 400

#Grab User Data for display function
@app.route("/get_user_data", methods=["GET"])
def get_user_data():
    try:
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"success": False, "message": "User ID is required"}), 400
        
        response = supabase.table("guest").select("*").eq("user_id", user_id).execute()
        if not response.data:
            return jsonify({"success": False, "message": "User not found"}), 404
        
        return jsonify({"success": True, "user_data": response.data[0]}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

#Change Password Function
@app.route("/change_password", methods=["POST"])
def change_password():
    try:
        #Get data from request
        data = request.get_json()
        #Checking for data recieved
        user_id = data.get("user_id")

        if not user_id:
            return jsonify({"success": False, "message": "User ID is required"}), 400

        current_pw = data.get("current_password")
        new_pw = data.get("new_password")

        # Validate input
        if not user_id or not current_pw or not new_pw:
            return jsonify({"success": False, "message": "Missing required fields"}), 400
        
        auth_user = supabase.auth.sign_in_with_password({
            "email": data.get("email"),
            "password": current_pw
        })

        if "error" in auth_user:
            return jsonify({"success": False, "message": "Invalid current password"}), 401

        try:
            #Get guest name for loggin purposes:
            response = supabase.table("guest").select("email").eq("user_id", user_id).execute()
            
            email = response.data[0]["email"]
        
            #Log activity into supabase
            supabase.table("logs").insert({
                "id": user_id,
                "email": email,
                "activity": f"{email} changed their password",
                "logged_time": timestamp
            }).execute()
        except Exception as e:
            print(e)
            return jsonify({"success": False, "message": "Error logging password change"}), 500
            
        # Update the user's password in Supabase Auth
        update_response = supabase.auth.update_user({"password": new_pw})

        if "error" in update_response:
            return jsonify({"success": False, "message": "Failed to update password in Supabase Auth"}), 500
        
        #Hash new passwordfor storage
        new_pw_hashed = hash_password(new_pw)

        #Updatenew password into database
        supabase.table("guest").update({"password_hash": new_pw_hashed}).eq("user_id", user_id).execute()

        return jsonify({"success": True, "message": "Password updated successfully"}), 200

    except Exception as e:
        print("Error:", e)
        return jsonify({"success": False, "message": str(e)}), 500

#Saving preference function
@app.route("/save_preferences", methods=["POST"])
def save_preferences():
    try:
        # Get JSON data
        data = request.json
        print("Received preference data: ", data) #Debugging purposes

        #Extracting user_id and preferences
        user_id = data.get("user_id")
        preferences = data.get("preferences")

        #Error checking for presence of fields
        if not user_id or not preferences:
            return jsonify({"success": False, "Message": "Missing id or preferences!"}), 400
        
        # Destructure preferences
        bed_type = preferences.get("bedType")
        room_view = preferences.get("roomView")
        floor_preference = preferences.get("floorPreference")
        additional_features = preferences.get("additionalFeatures", {})

        # Default additional features if not provided
        extra_pillows = additional_features.get("extraPillows", False)
        extra_beds = additional_features.get("extraBeds", False)
        extra_towels = additional_features.get("extraTowels", False)
        early_check_in = additional_features.get("earlyCheckIn", False)

        # Insert preferences into the room_preferences table
        response = supabase.table("room_preferences").upsert({
            "user_id": user_id,
            "bed_type": bed_type,
            "room_view": room_view,
            "floor_preference": floor_preference,
            "extra_pillows": extra_pillows,
            "extra_beds": extra_beds,
            "extra_towels": extra_towels,
            "early_check_in": early_check_in
        }).execute()

        # Check if there was an error in the response
        if 'error' in response:
            print("Supabase error:", response['error'])
            return jsonify({"success": False, "message": "Error saving preferences"}), 500

        return jsonify({"success": True, "message": "Preferences saved successfully!"}), 200

    except Exception as e:
        print("Error in save_preferneces: ", e)
        return jsonify({"Success": False,})

#Booking Room
@app.route("/book_room", methods=["POST"])
def book_room():  
    try:
        # parse input data
        data = request.json
        
        #Checking for required fields
        required_fields = ["user_id", "room_type", "check_in_date", "check_out_date"]
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"success": False, "message": f"Missing required field: {field}"}), 400

        #Detail extraction
        user_id = data.get("user_id")
        room_type = data.get("room_type")
        check_in_date = datetime.fromisoformat(data.get("check_in_date")).replace(tzinfo=timezone.utc)
        check_out_date = datetime.fromisoformat(data.get("check_out_date")).replace(tzinfo=timezone.utc)

        # Amenities
        extra_towels = data.get("ExtraTowels", False)
        room_service = data.get("RoomService", False)
        spa_access = data.get("SpaAccess", False)
        airport_pickup = data.get("AirportPickup", False)
        late_checkout = data.get("LateCheckout", False)
        
        # Check for available rooms of the specified type
        response = supabase.table("room").select("*").eq("room_type", room_type).execute()
        all_room = response.data
        if not all_room:
            return jsonify({"success": False, "message": "No available rooms of the selected type"}), 400

        suitable_room = None
        for room in all_room:
            # Check existing bookings for this room
            bookings_response = supabase.table("room_booking") \
                .select("check_in_date, check_out_date") \
                .eq("room_id", room["room_id"]) \
                .execute()
            
            # Check for overlapping bookings
            conflict = False
            for booking in bookings_response.data:
                existing_start = datetime.fromisoformat(booking["check_in_date"]).astimezone(timezone.utc)
                existing_end = datetime.fromisoformat(booking["check_out_date"]).astimezone(timezone.utc)
                
                # Check for date overlap
                if (check_in_date < existing_end) and (check_out_date > existing_start):
                    conflict = True
                    break
            
            if not conflict:
                suitable_room = room
                break

        if not suitable_room:
            return jsonify({"success": False, "message": "No available rooms for selected dates"}), 400

        # Book the room
        booking_data = {
            "user_id": user_id,
            "room_id": suitable_room["room_id"],
            "check_in_date": check_in_date.isoformat(),
            "check_out_date": check_out_date.isoformat(),
            "extra_towels": extra_towels,
            "room_service": room_service,
            "spa_access": spa_access,
            "airport_pickup": airport_pickup,
            "late_checkout": late_checkout
        }
        booking_response = supabase.table("room_booking").insert(booking_data).execute()

        if booking_response.data:
            # Update room status to "Occupied"
            supabase.table("room").update({"status": "Occupied"}).eq("room_id", suitable_room["room_id"]).execute()

            return jsonify({"success": True, "message": "Room booked successfully!", "room_number": suitable_room["room_number"]}), 200
        else:
            return jsonify({"success": False, "message": "Error booking room."}), 400
    
    except Exception as e:
        print("Error in book_room:", str(e))
        return jsonify({"success": False, "message": "Internal server error"}), 500

#Get booking list for display
@app.route('/get_guest_bookingsGUEST', methods=['GET'])
def get_guest_bookingsGUEST():
    try:
        response = supabase.table('room_booking') \
            .select('*, guest(first_name, last_name), room(room_type)') \
            .execute()

        bookings = response.data

        formatted_bookings = []
        for booking in bookings:
            formatted = {
                'id': booking['reservation_id'],
                'roomType': booking.get('room', {}).get('room_type', 'Unknown'),
                'checkInDate': booking['check_in_date'],
                'checkOutDate': booking['check_out_date'],
                'guestName': f"{booking.get('guest', {}).get('first_name', '')} "
                             f"{booking.get('guest', {}).get('last_name', '')}".strip(),
                'status': 'Checked In' if booking['checkin_status'] else 'Pending'
            }
            formatted_bookings.append(formatted)

        return jsonify(formatted_bookings), 200

    except Exception as e:
        print(f"Error retrieving guest bookings: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to retrieve bookings'}), 500

#Cancel Booking
@app.route('/cancel_booking/<int:booking_id>', methods=['DELETE'])
def cancel_booking(booking_id):
    try:
        booking_response = supabase.table('room_booking') \
            .select('*') \
            .eq('reservation_id', booking_id) \
            .execute()
        
        if not booking_response.data:
            return jsonify({'success': False, 'message': 'Booking not found'}), 404

        delete_response = supabase.table('room_booking') \
            .delete() \
            .eq('reservation_id', booking_id) \
            .execute()

        if delete_response.data:
            supabase.table('room') \
                .update({'status': 'Available'}) \
                .eq('room_id', booking_response.data[0]['room_id']) \
                .execute()
            
            return jsonify({'success': True, 'message': 'Booking canceled'}), 200
        
        return jsonify({'success': False, 'message': 'Failed to cancel booking'}), 400

    except Exception as e:
        print(f"Error canceling booking: {str(e)}")
        return jsonify({'success': False, 'message': 'Server error'}), 500

#Edit account details (Not password)
@app.route("/update_user", methods=["POST"])
def update_user():
    try:
        # Get JSON data
        data = request.json

        # Extract user ID and details
        user_id = data.get("user_id")
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        mobile_number = data.get("mobile_number")
        email = data.get("email")

        # Check for required fields
        if not user_id or not first_name or not last_name or not mobile_number or not email:
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        # Update the guest details
        response = supabase.table("guest").update({
            "first_name": first_name,
            "last_name": last_name,
            "mobile_number": mobile_number,
            "email": email
        }).eq("user_id", user_id).execute()

        if 'error' in response:
            print("Supabase error:", response['error'])
            return jsonify({"success": False, "message": "Error updating account details"}), 500

        return jsonify({"success": True, "message": "Account details updated successfully"}), 200

    except Exception as e:
        print("Error in edit_account_details:", e)
        return jsonify({"success": False, "message": "Internal server error"}), 500

@app.route("/edit_booking/<int:reservation_id>", methods=["PUT"])  # Changed to PUT and added URL parameter
def edit_booking(reservation_id):
    try:
        data = request.json

        # Validate input
        required_fields = ["check_in_date", "check_out_date"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "message": f"Missing {field}"}), 400

        # Convert dates to UTC
        try:
            new_check_in = datetime.fromisoformat(data["check_in_date"]).astimezone(timezone.utc)
            new_check_out = datetime.fromisoformat(data["check_out_date"]).astimezone(timezone.utc)
        except ValueError:
            return jsonify({"success": False, "message": "Invalid date format"}), 400

        # Validate date order
        if new_check_in >= new_check_out:
            return jsonify({"success": False, "message": "Check-out must be after check-in"}), 400

        # Get current booking
        booking_response = supabase.table("room_booking") \
            .select("room_id,check_in_date,check_out_date") \
            .eq("reservation_id", reservation_id) \
            .execute()
        
        if not booking_response.data:
            return jsonify({"success": False, "message": "Booking not found"}), 404

        current_booking = booking_response.data[0]
        room_id = current_booking["room_id"]

        # Check for overlapping bookings
        conflicts_response = supabase.table("room_booking") \
            .select("reservation_id,check_in_date,check_out_date") \
            .eq("room_id", room_id) \
            .neq("reservation_id", reservation_id) \
            .execute()

        conflict = False
        for booking in conflicts_response.data:
            existing_start = datetime.fromisoformat(booking["check_in_date"]).astimezone(timezone.utc)
            existing_end = datetime.fromisoformat(booking["check_out_date"]).astimezone(timezone.utc)
            
            if (new_check_in < existing_end) and (new_check_out > existing_start):
                conflict = True
                break

        if conflict:
            return jsonify({
                "success": False,
                "message": "Dates conflict with existing booking"
            }), 400

        # Prepare update data
        update_data = {
            "check_in_date": new_check_in.isoformat(),
            "check_out_date": new_check_out.isoformat()
        }

        # Update booking
        update_response = supabase.table("room_booking") \
            .update(update_data) \
            .eq("reservation_id", reservation_id) \
            .execute()

        if not update_response.data:
            return jsonify({"success": False, "message": "Update failed"}), 500

        return jsonify({
            "success": True,
            "message": "Booking updated successfully",
            "new_dates": update_data
        }), 200

    except Exception as e:
        print(f"Edit booking error: {str(e)}")
        return jsonify({"success": False, "message": "Server error"}), 500
    
""""
STAFF FUNCTIONS
"""
#Adding blacklisted guest to table
@app.route("/blacklist", methods=["POST"])
def blacklist():
    try:
        auth_header = request.headers.get("Authorization")  # Get token from headers
        if not auth_header or not auth_header.startswith("Bearer "):
            return {"message": "Missing or invalid token"}, 401

        token = auth_header.split("Bearer ")[1]
        
        response_dict = json.loads(token)

        access_token = response_dict.get('session', {}).get('access_token', None)

        user_repsonse = supabase.auth.get_user(access_token)

        staff_id = user_repsonse.user.id

        data = request.json
        email = data.get("email")
        reason = data.get("reason")

        if not email or not reason:
            return jsonify({"sucess": False, "message": "Email and reason are required."}), 400
        
        guest_response = supabase.table("guest").select("*").eq("email", email).execute()
        if not guest_response.data:
            return jsonify({"sucess": False, "message": "Guest not found."}), 400
        
        blacklist_response = supabase.table("blacklist").insert({
            "email": email,
            "reason": reason,
            "added_by": staff_id
        }).execute()

        if blacklist_response.data:
            return jsonify({"sucess": True, "message": "Guest successfully blacklisted."}), 200
        else:
            return jsonify({"success": False, "message": "Error adding guest to blacklist."}), 4
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

#fetch all blacklisted guest
@app.route('/get_blacklisted_guests', methods=['GET'])
def get_blacklisted_guests():
    try:
        # Fetch blacklisted guests from the database
        response = supabase.table("blacklist").select("*").execute()
        
        # Log the full Supabase response for debugging
        print("Supabase Response:", response)
        
        # Check if the response has a 'data' field and is not empty
        if hasattr(response, 'data') and response.data:
            return jsonify({
                'blacklistedGuests': [
                    {'guestEmail': guest['email'], 'reason': guest['reason']}
                    for guest in response.data
                ]
            }), 200
        else:
            # Check if the response contains an error
            if hasattr(response, 'error') and response.error:
                print("Supabase Error:", response.error)
                return jsonify({"error": response.error.message}), 500
            else:
                return jsonify({"message": "Currently no blacklisted guests found"}), 404
    except Exception as e:
        # Return error details to help debugging
        print("Exception:", e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

#Fetch all bookings
@app.route('/get_guest_bookings', methods = ['GET'])
def get_guest_bookings():
    try:
        response = supabase.table('room_booking') \
                    .select('*, guest( first_name, last_name )').execute()

        bookings = response.data

        pending = []
        checked_in = []

        for booking in bookings:
            guest = booking.get('guest', {})
            booking_data = {
                'id': booking['reservation_id'],
                'name': f"{guest.get('first_name', '')} {guest.get('last_name', '')}".strip(),
                'checkInDate': booking['check_in_date'] if booking['checkin_status'] else "-",
                'checkOutDate': booking['check_out_date'] if booking['checkin_status'] else "-"
            }
            
            if booking['checkin_status']:
                checked_in.append(booking_data)
            else:
                pending.append(booking_data)
                
        return jsonify({
            'pending': pending,
            'checkedIn': checked_in
        }), 200
    
    except Exception as e:
        print(f"Error retrieving guest bookings: {str(e)}")
        return jsonify({'suess': False, 'message': 'failed to retrieve room bookings'})

# checks guess out
@app.route('/check_out/<int:booking_id>', methods=['DELETE'])  # Changed to DELETE method
def check_out(booking_id):
    try:
        booking_response = supabase.table('room_booking') \
            .select('room_id') \
            .eq('reservation_id', booking_id) \
            .execute()
        
        if not booking_response.data:
            return jsonify({'success': False, 'message': 'Booking not found'}), 404

        delete_response = supabase.table('room_booking') \
            .delete() \
            .eq('reservation_id', booking_id) \
            .execute()

        if delete_response.data:
            supabase.table('room') \
                .update({'status': 'Available'}) \
                .eq('room_id', booking_response.data[0]['room_id']) \
                .execute()
            
            return jsonify({'success': True, 'message': 'Check-out successful'}), 200
            
        return jsonify({'success': False, 'message': 'Check-out failed'}), 400

    except Exception as e:
        print(f"Check-out error: {str(e)}")
        return jsonify({'success': False, 'message': 'Server error'}), 500
    
""""
ADMIN FUNCTION
"""
@app.route('/get_all_staff', methods=['GET'])
def get_all_staff():
    try:
        response =supabase.table("profiles").select("id").eq("role", "staff").execute()
        staffId = response.data

        staff = []
        
        for staff_id in staffId:
            staff_response = supabase.table("employee").select("*").eq("id", staff_id["id"]).execute()
            
            if staff_response.data:
                staff.append(staff_response.data[0])
            
        return jsonify(staff), 200
        
    except Exception as e:
        print(f"Error retrieving staff: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to retrieve staff'}), 500

@app.route("/add_staff", methods=["POST"])
def add_staff():
    try:
        # Get JSON data from frontend
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"success": False, "message": "Email and password are required"}), 400

        try:
            # Create a new user in Supabase Auth
            auth_response = supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True  # Auto-confirm email
            })
            
            # Check for valid response
            if not hasattr(auth_response, 'user') or not auth_response.user.id:
                return jsonify({"success": False, "message": "Failed to create auth user"}), 500
                
            user_id = auth_response.user.id
        except Exception as e:
            print(f"Error creating user in Supabase Auth: {str(e)}")

        # Insert staff details into profiles table
        profiles_response = supabase.table("profiles").insert({
            "id": user_id,
            "role": "staff"
        }).execute()
        
        employee_response = supabase.table("employee").insert({
            "id": user_id,
            "email": email,
            "full_name": "AnonStaff",
            "password_hash": hash_password(password),
            "active_status": True
        }).execute()
        
        return jsonify({"success": True, "message": "Staff added successfully"}), 201

    except Exception as e:
        print(f"Error adding staff: {str(e)}")
        return jsonify({"success": False, "message": "Error adding staff"}), 500

@app.route("/delete_staff/<string:staff_id>", methods=["DELETE"])
def delete_staff(staff_id):
    try:
        # Delete staff from profiles table
        profiles_response = supabase.table("profiles").delete().eq("id", staff_id).execute()
        
        # Delete staff from employee table
        employee_response = supabase.table("employee").delete().eq("id", staff_id).execute()
        
        # Delete staff from Supabase Auth
        auth_response = supabase.auth.admin.delete_user(staff_id)
        
        return jsonify({"success": True, "message": "Staff deleted successfully"}), 200

    except Exception as e:
        print(f"Error deleting staff: {str(e)}")
        return jsonify({"success": False, "message": "Error deleting staff"}), 500

@app.route("/retrieve_logs", methods=["GET"])
def retrieve_logs():
    try:
        response = supabase.table("logs").select("*").execute()
        logs = response.data

        return jsonify(logs), 200

    except Exception as e:
        print(f"Error retrieving logs: {str(e)}")
        return jsonify({"success": False, "message": "Error retrieving logs"}), 500
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
