from flask import Flask, request, jsonify
from supabase import create_client, Client
from flask_cors import CORS
import hashlib
import os

# Supabase connection setup
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

app = Flask(__name__)
CORS(app)

#Hash Function
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

#Registration Function
@app.route("/register", methods=["POST"])
def register():
    try:
        # Get the data from the frontend
        data = request.get_json()
        
        # Debugging purposes (Delete later)
        print("Received data:", data)
        
        #Filling in variables
        first_name = data.get("firstName")
        last_name = data.get("lastName")
        mobile_number = data.get("phoneNum")
        email = data.get("email")
        password_hash = hash_password(data.get("password"))
        facialID_consent = False
        
        #creating user in supabase authentication 
        auth_response = supabase.auth.sign_up({
                "email": email,
                "password": data.get("password"),
                "options": {"data": 
                    {
                        "first_name": first_name, 
                        "last_name": last_name, 
                        "mobile_number": mobile_number
                    }
                }     
            }  
        )
        
        user_id = auth_response.user.id
        
        # No facial opt in
        if data.get("facialRecognitionOptIn") == False:
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
            # Check response after insertion
            if guest_response.data:
                return jsonify({"success": True, "message": "Registration successful!"}), 200
            else:
                return jsonify({"success": False, "message": "Error inserting into guest table."}), 400
        
        # Facial opt in  
        elif data.get("optInFacialRecognition") == True:
            # Facial data insertion + Account registration
            return jsonify({"success": True, "message": "Facial recognition opted-in"}), 200
        
        #something went wrong
        else: 
            return jsonify({"success": False, "message": "Something Went wrong"}), 400
        
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
@app.route("/change_password", methods=["post"])
def change_password():
    try:
        #Get data from request
        data = request.get_json()
        #Checking for data recieved
        print("Received Data: ", data)
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
        print("Data recieved:", data)

        #Checking for required fields
        required_fields = ["user_id", "room_type", "check_in_date", "check_out_date"]
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"success": False, "message": f"Missing required field: {field}"}), 400

        #Detail extraction
        user_id = data.get("user_id")
        room_type = data.get("room_type")
        check_in_date = data.get("check_in_date")
        check_out_date = data.get("check_out_date")

        # Amenities
        extra_towels = data.get("ExtraTowels", False)
        room_service = data.get("RoomService", False)
        spa_access = data.get("SpaAccess", False)
        airport_pickup = data.get("AirportPickup", False)
        late_checkout = data.get("LateCheckout", False)
        
        # Check for available rooms of the specified type
        response = supabase.table("room").select("*").eq("room_type", room_type).eq("status", "Available").execute()
        available_rooms = response.data
        if not available_rooms:
            return jsonify({"success": False, "message": "No available rooms of the selected type"}), 400

        # Check for date clashes
        suitable_room = None
        for room in available_rooms:
            room_id = room["room_id"]
            booking_conflicts = supabase.table("room_booking").select("*").eq("room_id", room_id).execute()
            conflicts = booking_conflicts.data

            # Check if the room is free for the selected dates
            is_available = all(
                (check_out_date <= booking["check_in_date"] or check_in_date >= booking["check_out_date"])
                for booking in conflicts
            )
            if is_available:
                suitable_room = room
                break

        if not suitable_room:
            return jsonify({"success": False, "message": "No rooms available for the selected dates"}), 400

        # Book the room
        booking_data = {
            "user_id": user_id,
            "room_id": suitable_room["room_id"],
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
