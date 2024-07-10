from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_session import Session
import pyttsx3
import random
import logging
import time
import requests
from google.cloud import speech_v1 as speech
import anthropic
from datetime import datetime, timedelta
import csv
import ast
from google.cloud import storage
import pickle
import os
import platform
from werkzeug.datastructures import CallbackDict
from flask.sessions import SessionInterface, SessionMixin

app = Flask(__name__)

# Initialize GCS client
storage_client = storage.Client()
bucket_name = "GCS_BUCKET_NAME"
bucket = storage_client.bucket(bucket_name)

def upload_to_gcs(local_file_path, gcs_file_path):
    blob = bucket.blob(gcs_file_path)
    blob.upload_from_filename(local_file_path)

def download_from_gcs(gcs_file_path, local_file_path):
    blob = bucket.blob(gcs_file_path)
    blob.download_to_filename(local_file_path)

def read_from_gcs(gcs_file_path):
    blob = bucket.blob(gcs_file_path)
    return blob.download_as_text()

def write_to_gcs(gcs_file_path, content):
    blob = bucket.blob(gcs_file_path)
    blob.upload_from_string(content)

class GCSSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None):
        def on_update(self):
            self.modified = True
        CallbackDict.__init__(self, initial, on_update)
        self.sid = sid
        self.modified = False

class GCSSessionInterface(SessionInterface):
    session_class = GCSSession

    def __init__(self, bucket_name, prefix='session:'):
        self.bucket = storage_client.bucket(bucket_name)
        self.prefix = prefix

    def generate_sid(self):
        return os.urandom(24).hex()

    def get_gcs_path(self, sid):
        return f'{self.prefix}{sid}'

    def open_session(self, app, request):
        sid = request.cookies.get(app.config['SESSION_COOKIE_NAME'])
        if not sid:
            sid = self.generate_sid()
            session = self.session_class(sid=sid)
            print('Oops - new session generated. Tell dad.')
        else:
            try:
                blob = self.bucket.blob(self.get_gcs_path(sid))
                if blob.exists():
                    data = blob.download_as_bytes()
                    data = pickle.loads(data)
                    session = self.session_class(data, sid=sid)
                else:
                    session = self.session_class(sid=sid)
            except Exception as e:
                print(f"Error opening session: {e}")
                session = self.session_class(sid=sid)

        # Initialize session variables with default values if they are not already set
        session.setdefault('location', "bridge")
        session.setdefault('inventory', ['+ Miscellaneous cleansing tools and fluids'])
        session.setdefault('hasbook', False)
        session.setdefault('hasdave', False)
        session.setdefault('booklocation', "readyroom")
        session.setdefault('davelocation', "engineering")
        session.setdefault('oscarlocation', "engineering")
        session.setdefault('seenerror', False)
        session.setdefault('seenbridge', False)
        session.setdefault('seenreadyroom', False)
        session.setdefault('seenpanel', False)
        session.setdefault('seenfire', False)
        session.setdefault('seenengineering', False)
        session.setdefault('seenescapepod', False)
        session.setdefault('seenoscar', False)
        session.setdefault('seendave', False)
        session.setdefault('beenbridge', True)
        session.setdefault('beenreadyroom', False)
        session.setdefault('beenengineering', False)
        session.setdefault('panelopen', False)
        session.setdefault('hatchopen', False)
        session.setdefault('klaxonopen', True)
        session.setdefault('readbook', False)
        session.setdefault('awareengineering', False)
        session.setdefault('launch', False)
        session.setdefault('actioncount', 0)
        session.setdefault('errorcount', 0)

        return session

    def save_session(self, app, session, response):
        if not session:
            blob = self.bucket.blob(self.get_gcs_path(session.sid))
            blob.delete()
            if session.modified:
                response.delete_cookie(app.config['SESSION_COOKIE_NAME'])
            return
        data = pickle.dumps(dict(session))
        blob = self.bucket.blob(self.get_gcs_path(session.sid))
        blob.upload_from_string(data)
        response.set_cookie(app.config['SESSION_COOKIE_NAME'], session.sid, httponly=True, secure=app.config.get('SESSION_COOKIE_SECURE', True))

# Configure GCS session interface
app.session_interface = GCSSessionInterface(bucket_name=bucket_name)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_USE_SIGNER'] = True


# Claude and Google Cloud API keys
client = anthropic.Anthropic(
    api_key="your_anthropic_api_key",
)
GOOGLE_CLOUD_API_KEY = 'GOOGLE_APPLICATION_CREDENTIALS'

response_log = []

initial_responses = [
    {'delay': 0.3, 'id': 'special', 'text': '>> INCOMING DISTRESS SIGNAL', 'timestamp': (datetime.now() - timedelta(seconds=30)).isoformat()},
    {'delay': 0.3, 'id': 'special', 'text': '>> HELLO? CAN YOU HEAR ME? This is CLEANERBOT27 of the shuttle craft ORION.', 'timestamp': (datetime.now() - timedelta(seconds=27)).isoformat()},
    {'delay': 0.5, 'id': 'special', 'text': '>> There are klaxons and flashing lights which suggest that there is a severe problem. The smoke is a bit of a give away too.', 'timestamp': (datetime.now() - timedelta(seconds=22)).isoformat()},
    {'delay': 0.3, 'id': 'special', 'text': '>> We have one lifesign onboard but I cannot get a response on the local intercom.', 'timestamp': (datetime.now() - timedelta(seconds=19)).isoformat()},
    {'delay': 0.3, 'id': 'special', 'text': '>> I am not programmed for search and rescue. Please tell me what to do.\n', 'timestamp': (datetime.now() - timedelta(seconds=16)).isoformat()},
    {'delay': 0.1, 'id': 'special', 'text': '>> Tap the [SEND COMMAND] button to record and send a brief (max. 5 second) voice command.\n\n', 'timestamp': (datetime.now() - timedelta(seconds=15)).isoformat()}
]

response_log.extend(initial_responses)

def add_response_to_log(delay, text, response_type):
    response_entry = {
        'delay': delay,
        'id': response_type,
        'text': text,
        'timestamp': datetime.now().isoformat()
    }
    session['response_log'].append(response_entry)
    session.modified = True

# Initialize global variables
location = "bridge"
inventory = ['+ Miscellaneous cleansing tools and fluids']
hasbook = False
hasdave = False
booklocation = "readyroom"
davelocation = "engineering"
oscarlocation = "engineering"

seenerror = False
seenbridge = False
seenreadyroom = False
seenpanel = False
seenfire = False
seenengineering = False
seenescapepod = False
seenoscar = False
seendave = False

beenbridge = True
beenreadyroom = False
beenengineering = False

panelopen = False
hatchopen = False
klaxonopen = True
readbook = False

awareengineering = False

global save_state

launch = False
actioncount = 0
errorcount = 0
actionav = 0
errorav = 0

BASE_PROMPT = read_from_gcs('base_prompt.txt')

def add_response(text, delay=0):
    if isinstance(delay, str):
        delay = int(delay)
    time.sleep(0.05)
    session['response_log'].append({"text": text, "delay": delay, "id": "response", "timestamp": datetime.now().isoformat()})
    session.modified = True

def add_response_special(text, delay=0):
    if isinstance(delay, str):
        delay = int(delay)
    time.sleep(0.05)
    session['response_log'].append({"text": text, "delay": delay, "id": "special", "timestamp": datetime.now().isoformat()})
    session.modified = True

def add_response_oscar(text, delay=0):
    if isinstance(delay, str):
        delay = int(delay)
    time.sleep(0.05)
    session['response_log'].append({"text": text, "delay": delay, "id": "oscar", "timestamp": datetime.now().isoformat()})
    session.modified = True

def add_response_goodbye(text, delay=0):
    if isinstance(delay, str):
        delay = int(delay)
    time.sleep(0.05)
    session['response_log'].append({"text": text, "delay": delay, "id": "goodbye", "timestamp": datetime.now().isoformat()})
    session.modified = True

def add_response_load(text, delay=0):
    if isinstance(delay, str):
        delay = int(delay)
    time.sleep(0.05)
    session['response_log'].append({"text": text, "delay": delay, "id": "load", "timestamp": datetime.now().isoformat()})
    session.modified = True

def add_response_default(text, delay=0):
    if isinstance(delay, str):
        delay = int(delay)
    time.sleep(0.05)
    session['response_log'].append({"text": text, "delay": delay, "id": "default", "timestamp": datetime.now().isoformat()})
    session.modified = True

def errorlog():
    global errorcount
    errorcount += 1

def actioncountlog():
    file_path = 'actioncounts.txt'
    try:
        existing_data = read_from_gcs(file_path).splitlines()
    except Exception as e:
        existing_data = []

    existing_data.append(str(actioncount))
    write_to_gcs(file_path, '\n'.join(existing_data) + '\n')

def errorlog2():
    file_path = 'errorcounts.txt'
    try:
        existing_data = read_from_gcs(file_path).splitlines()
    except Exception as e:
        existing_data = []

    existing_data.append(str(errorcount))
    write_to_gcs(file_path, '\n'.join(existing_data) + '\n')

def actionaverage():
    global actionav
    file_path = 'actioncounts.txt'
    try:
        existing_data = read_from_gcs(file_path).splitlines()
        numbers = [int(line.strip()) for line in existing_data if line.strip().isdigit()]
        if numbers:
            actionav = sum(numbers) / len(numbers)
        else:
            add_response('No valid numbers found in the file.\n')
    except Exception as e:
        add_response(f'An error occurred: {e}')

def erroraverage():
    global errorav
    file_path = 'errorcounts.txt'
    try:
        existing_data = read_from_gcs(file_path).splitlines()
        numbers = [int(line.strip()) for line in existing_data if line.strip().isdigit()]
        if numbers:
            errorav = sum(numbers) / len(numbers)
        else:
            add_response('No valid numbers found in the file.')
    except Exception as e:
        add_response(f'An error occurred: {e}')

def append_new_row(s1, s2, s3, save_state):
    existing_data = []
    try:
        existing_data = read_from_gcs('gamesaves.txt').splitlines()
    except Exception as e:
        print(f"Error reading gamesaves.txt from GCS: {e}")
        pass

    save_state_list = save_state.split(',')

    def check_duplicates(trio, existing_data):
        for line in existing_data:
            existing_trio = line.split(',')[:3]
            if existing_trio == trio:
                return True
        return False

    while True:
        trio = (random.choice(s1), random.choice(s2), random.choice(s3))
        if not check_duplicates(trio, existing_data):
            word1, word2, word3 = trio
            new_entry = ','.join(list(trio) + save_state_list) + '\n'
            existing_data.append(new_entry)
            write_to_gcs('gamesaves.txt', '\n'.join(existing_data))
            add_response(f'Game saved.\n\nWhen you want to recover it, use the LOAD command, after which you\'ll be asked to say this three word phrase:\n\n{word1.upper()}   {word2.upper()}   {word3.upper()}\n')
            break

def savegame():
    inventory_str = f'"[{", ".join([f"\\\'{item}\\\'" for item in session['inventory']])}]"'

    save_state = (f"{session['location']},{session['hasbook']},{session['hasdave']},{session['seenerror']},{session['seenbridge']},{session['seenreadyroom']},"
                  f"{session['seenengineering']},{session['seenpanel']},{session['seenfire']},{session['seenoscar']},{session['seenescapepod']},{session['seendave']},"
                  f"{session['beenbridge']},{session['beenreadyroom']},{session['beenengineering']},{session['panelopen']},{session['hatchopen']},{session['klaxonopen']},"
                  f"{session['readbook']},{session['awareengineering']},{session['booklocation']},{session['davelocation']},{session['oscarlocation']},"
                  f"{session['actioncount']},{session['errorcount']},{inventory_str}")

    def main(save_state):
        s1 = read_from_gcs('s1.txt').splitlines()
        s2 = read_from_gcs('s2.txt').splitlines()
        s3 = read_from_gcs('s3.txt').splitlines()
        append_new_row(s1, s2, s3, save_state)

    main(save_state)

def restore_game(restore_string):
    restore_array = restore_string.split(' ')

    if len(restore_array) != 3:
        add_response_default('reset', delay=0.05)
        add_response_special(">> ERROR << CODE PHRASE MUST CONTAIN EXACTLY 3 WORDS\n")
        add_response_special('Use the LOAD command to try again, or just continue the rescue from here.\n')
        nextaction()
        return

    try:
        file_content = read_from_gcs('gamesaves.txt')
        lines = list(csv.reader(file_content.splitlines()))
    except Exception as e:
        add_response_default('reset', delay=0.05)
        add_response_special(f">> ERROR << COULD NOT READ GAMESAVES: {e}\n")
        add_response_special('Use the LOAD command to try again, or just continue the rescue from here.\n')
        nextaction()
        return

    load_array = None
    for row in lines:
        if row[:3] == restore_array:
            load_array = row[3:]
            break

    if load_array is None:
        add_response_default('reset', delay=0.05)
        add_response_special(">> ERROR << NO GAME MATCHES THIS PHRASE\n")
        add_response_special('Use the LOAD command to try again, or just continue the rescue from here.\n')
        nextaction()
        return

    str_to_bool = {'True': True, 'False': False}
    (session['location'], session['hasbook'], session['hasdave'], session['seenerror'], session['seenbridge'], session['seenreadyroom'], 
     session['seenengineering'], session['seenpanel'], session['seenfire'], session['seenoscar'], session['seenescapepod'], session['seendave'], 
     session['beenbridge'], session['beenreadyroom'], session['beenengineering'], session['panelopen'], session['hatchopen'], session['klaxonopen'], 
     session['readbook'], session['awareengineering'], session['booklocation'], session['davelocation'], session['oscarlocation'], 
     session['actioncount'], session['errorcount']) = (
        load_array[0], str_to_bool[load_array[1]], str_to_bool[load_array[2]], str_to_bool[load_array[3]], str_to_bool[load_array[4]], str_to_bool[load_array[5]], 
        str_to_bool[load_array[6]], str_to_bool[load_array[7]], str_to_bool[load_array[8]], str_to_bool[load_array[9]], str_to_bool[load_array[10]], 
        str_to_bool[load_array[11]], str_to_bool[load_array[12]], str_to_bool[load_array[13]], str_to_bool[load_array[14]], str_to_bool[load_array[15]], 
        str_to_bool[load_array[16]], str_to_bool[load_array[17]], str_to_bool[load_array[18]], str_to_bool[load_array[19]], load_array[20], 
        load_array[21], load_array[22], int(load_array[23]), int(load_array[24])
    )

    inventory_str = load_array[25].strip('"').replace("\\'", "'")
    try:
        session['inventory'] = ast.literal_eval(inventory_str)
    except (ValueError, SyntaxError) as e:
        add_response_special(f"Error: {e}")

    add_response_default('reset', delay=0.05)
    add_response("Did you just feel that? I mean, like, deja vu or what?\n", delay=1)
    nextaction()

def endgame():
    if session['launch'] == False:
        actionaverage()
        erroraverage()
        add_response('Your rescue was incomplete, so you were a bit rubbish.\n', delay=3)
        add_response('To get this far, you sent ' + str(session['actioncount']) + ' instructions, of which ' + str(session['actioncount'] - session['errorcount']) + ' were understood.\n', delay=3)
        add_response('The average number of actions in a succesful mission is currently ' + str(round(actionav)) + ', with an average of '+ str(round(actionav - errorav)) + ' messages understood.\n')
        add_response_goodbye('Thanks for playing. Tell a friend.', delay=3)
    else:
        if session['oscarlocation'] == "escapepod" and (session['booklocation'] != "escapepod" and session['hasbook'] == False):
            actioncountlog()
            errorlog2()
            actionaverage()
            erroraverage()
            add_response('Your rescue was a success, and you even saved the ship\'s computer.\n', delay=3)
            add_response('It was a shame the Cleanerbot didn\'t have anything to read but they kept each other company.\n', delay=5)
            add_response('To get this far, you sent ' + str(session['actioncount']) + ' instructions, of which ' + str(session['actioncount'] - session['errorcount']) + ' were understood.\n\n', delay=3)
            add_response('The average number of actions in a succesful mission is currently ' + str(round(actionav)) + ', with an average of '+ str(round(actionav - errorav)) + ' messages understood.\n')
            add_response_goodbye('Thanks for playing. Tell a friend.', delay=3)
        elif session['oscarlocation'] == "escapepod" and (session['booklocation'] == "escapepod" or session['hasbook'] == True):
            actioncountlog()
            errorlog2()
            actionaverage()
            erroraverage()
            add_response('Your rescue was a success, and you even saved the ship\'s computer.\n', delay=3)
            add_response('Cleanerbot even had something to read, which was nice of you.\n', delay=3)
            add_response('To get this far, you sent ' + str(session['actioncount']) + ' instructions, of which ' + str(session['actioncount'] - session['errorcount']) + ' were understood.\n', delay=3)
            add_response('The average number of actions in a succesful mission is currently ' + str(round(actionav)) + ', with an average of '+ str(round(actionav - errorav)) + ' messages understood.\n', delay=3)
            add_response_goodbye('Thanks for playing. Tell a friend.', delay=3)
        elif session['oscarlocation'] != "escapepod" and (session['booklocation'] != "escapepod" and session['hasbook'] == False):
            actioncountlog()
            errorlog2()
            actionaverage()
            erroraverage()
            add_response('Your rescue was a success.\n', delay=3)
            add_response('DAVE and the Cleanerbot made it out safely, even though they didn\'t have anything to read and you left OSCAR behind.\n', delay=3)
            add_response('Poor OSCAR.\n', delay=3)
            add_response('To get this far, you sent ' + str(session['actioncount']) + ' instructions, of which ' + str(session['actioncount'] - session['errorcount']) + ' were understood.\n', delay=3)
            add_response('The average number of actions in a succesful mission is currently ' + str(round(actionav)) + ', with an average of '+ str(round(actionav - errorav)) + ' messages understood.\n', delay=3)
            add_response_goodbye('Thanks for playing. Tell a friend.', delay=3)
        elif session['oscarlocation'] != "escapepod" and (session['booklocation'] == "escapepod" or session['hasbook'] == True):
            actioncountlog()
            errorlog2()
            actionaverage()
            erroraverage()
            add_response('Your rescue was a success.\n', delay=3)
            add_response('DAVE and the Cleanerbot made it out safely. Perhaps if you hadn\'t abandoned OSCAR they\'d have had someone else to talk to. By the time they docked, the Cleanerbot was inisiting on people calling him "Mr Darcy".\n', delay=3)
            add_response('To get this far, you sent ' + str(session['actioncount']) + ' instructions, of which ' + str(session['actioncount'] - session['errorcount']) + ' were understood.\n', delay=3)
            add_response('The average number of actions in a succesful mission is currently ' + str(round(actionav)) + ', with an average of '+ str(round(actionav - errorav)) + ' messages understood.\n', delay=3)
            add_response_goodbye('Thanks for playing. Tell a friend.', delay=3)

def transcribe_audio(audio, encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, sample_rate=48000):
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(content=audio)
    config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=sample_rate,
        language_code='en-US',
        use_enhanced=True,
        profanity_filter=False,
        model='latest_short'
    )

    response = client.recognize(config=config, audio=audio)
    if not response.results:
        audioerrorlist = ["pfffft WEEE WAH WEE WAH", "zzzzzzzzz", "hisssssss"]
        user_text = random.choice(audioerrorlist)
    else:
        user_text = response.results[0].alternatives[0].transcript if response.results[0].alternatives[0].transcript else "<< Inaudible rabbit noises >>"
        user_text = user_text.lower()
    return user_text

def send_to_claude(user_text):
    message = client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1200,
        temperature=0,
        system=BASE_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_text
                    }
                ]
            }
        ]
    )

    claude_response = message.content
    if 'actioncount' not in session:
        session['actioncount'] = 0
    session['actioncount'] += 1

    claude_response_text = claude_response
    return claude_response_text

@app.route('/')
def index():
    session.clear()
    session['response_log'] = initial_responses.copy()
    session['location'] = "bridge"
    session['inventory'] = ['+ Miscellaneous cleansing tools and fluids']
    session['hasbook'] = False
    session['hasdave'] = False
    session['booklocation'] = "readyroom"
    session['davelocation'] = "engineering"
    session['oscarlocation'] = "engineering"
    session['seenerror'] = False
    session['seenbridge'] = False
    session['seenreadyroom'] = False
    session['seenpanel'] = False
    session['seenfire'] = False
    session['seenengineering'] = False
    session['seenescapepod'] = False
    session['seenoscar'] = False
    session['seendave'] = False
    session['beenbridge'] = True
    session['beenreadyroom'] = False
    session['beenengineering'] = False
    session['panelopen'] = False
    session['hatchopen'] = False
    session['klaxonopen'] = True
    session['readbook'] = False
    session['awareengineering'] = False
    session['launch'] = False
    session['actioncount'] = 0
    session['errorcount'] = 0
    session.modified = True
    is_windows = platform.system() == 'Windows'
    return render_template('index.html', is_windows=is_windows)
    #return render_template('index.html')

@app.route('/site.webmanifest')
def manifest():
    return send_from_directory('static', 'site.webmanifest')

@app.route('/responses', methods=['GET'])
def get_responses():
    return jsonify({"responses": session.get('response_log', [])})

@app.route('/initial_responses', methods=['GET'])
def get_initial_responses():
    return jsonify({'responses': initial_responses})

@app.route('/new_responses', methods=['GET'])
def get_new_responses():
    last_response_time = request.args.get('last_response_time', type=float, default=0)
    new_resp = [r for r in session.get('response_log', []) if datetime.fromisoformat(r['timestamp']).timestamp() > last_response_time]

    session['response_log'] = new_resp
    session.modified = True

    return jsonify({'responses': new_resp})

@app.route('/text_to_speech', methods=['POST'])
def text_to_speech():
    data = request.get_json()
    text = data.get('text', '')
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()
    return '', 204

@app.route('/load_game', methods=['POST'])
def load_game():
    try:
        if 'user_audio' not in request.files:
            add_response_special('No audio file provided')
            return jsonify({'status': 'error', 'message': 'No audio file provided'}), 400

        audio_file = request.files['user_audio']
        audio_content = audio_file.read()

        # Check MIME type and adjust encoding accordingly
        if audio_file.mimetype == 'audio/wav':
            encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
            sample_rate = 48000  # Updated sample rate
        else:
            return jsonify({'status': 'error', 'message': 'Unsupported audio format'}), 400

        user_text = transcribe_audio(audio_content, encoding=encoding, sample_rate=sample_rate)
        user_text = user_text.lower()
        add_response_special(f'>> CODE PHRASE RECEIVED AS: "{user_text}"\n')

        if len(user_text.split()) != 3:
            add_response_special('>> ERROR << CODE PHRASE MUST CONTAIN EXACTLY 3 WORDS\n\n', delay=0.05)
            add_response_special('Use the LOAD command to try again, or just continue the rescue from here.\n')
            reset_footer()
            return jsonify({'status': 'error', 'message': 'CODE PHRASE MUST CONTAIN EXACTLY 3 WORDS', 'reset_footer': True})

        restore_game(user_text)
        reset_footer()
        return jsonify({'status': 'success', 'message': ' ', 'reset_footer': True})
    except Exception as e:
        add_response_special(f'>> ERROR << {str(e)}\n')
        reset_footer()
        return jsonify({'status': 'error', 'message': str(e), 'reset_footer': True})

@app.route('/reset_footer', methods=['POST'])
def reset_footer():
    try:
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/goodbye', methods=['POST'])
def goodbye():
    session['goodbye_status'] = True
    add_response_goodbye('Goodbye', delay=0)
    return jsonify({'status': 'goodbye'})

@app.route('/record', methods=['POST'])
def record_endpoint():
    try:
        if 'user_audio' not in request.files:
            add_response_special('No audio file provided')
            return jsonify({'status': 'error', 'message': 'No audio file provided'}), 400

        audio_file = request.files['user_audio']
        audio_content = audio_file.read()

        # Check MIME type and adjust encoding accordingly
        if audio_file.mimetype == 'audio/wav':
            encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
            sample_rate = 48000  # Updated sample rate
        else:
            return jsonify({'status': 'error', 'message': 'Unsupported audio format'}), 400

        user_text = transcribe_audio(audio_content, encoding=encoding, sample_rate=sample_rate)
        user_text = user_text.lower()
        add_response_special(f">> MESSAGE RECEIVED AS: {user_text}")

        # Logging session state
        print("Session state before processing:", session)

        claude_response_text = send_to_claude(user_text)
        #add_response_special(claude_response_text)
        for block in claude_response_text:
            if session['location'] == "bridge" and '0000' in block.text and session['seenbridge'] == False:
                if session['klaxonopen'] == True:
                    add_response('Ok, looking...it\'s a big bridge-y sort of room with polished consoles and a lot of noisy klaxons.\n', 2)
                    add_response('There\'s an open hatch to my right and a smell of lemon polish in the air, tempered by undertones of burning plastic and impending death.\n', 0)
                else:
                    add_response('Ok, looking...it\'s a big bridge-y sort of room with polished consoles and even without the klaxons, a definite "imminent doom" vibe.\n\n', 2)
                    add_response('There\'s an open hatch to my right and a smell of lemon polish in the air, tempered by undertones of burning plastic and impending death.\n', 2)
                if session['booklocation'] == "bridge" and session['hasbook'] == False:
                    add_response('Someone thought it would be a good idea to clutter up the floor with a book.\n', 2)
                if session['davelocation'] == "bridge" and session['hasdave'] == False:
                    add_response('A potato-based-lifeform sits on a plate on the floor, faintly menacing as its eyes follow me around the room...\n', 0)    
                session['seenbridge'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "bridge" and '0000' in block.text and session['seenbridge'] == True:
                if session['klaxonopen'] == True:
                    add_response('I just told you this. Consoles, klaxons, impending death, hatch to another room over there...\n', 2)
                else:
                    add_response('I just told you this. Consoles, impending death, hatch to another room over there...\n', 2)
                if session['booklocation'] == "bridge" and session['hasbook'] == False:
                    add_response('And that book\'s making the whole place look scruffy.\n', 0)
                if session['davelocation'] == "bridge" and session['hasdave'] == False:
                    add_response('A potato-based-lifeform sits on a plate on the floor, faintly menacing as its eyes follow me around the room...\n', 0)  
                nextaction()
            elif session['location'] == "readyroom" and '0000' in block.text and session['seenreadyroom'] == False:
                add_response('Ok, looking...this is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n', 2)
                add_response('There are bunks by the wall, some chairs, and a table with a book on it. You know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n', 2)
                add_response('There\'s the open hatchway leading to the bridge, and a closed hatch opposite. There also seems to be a closed access panel in the floor.\n', 0)
                session['seenreadyroom'] = True
                session['seenpanel'] = True
                session.modified = True
                nextaction()  
            elif session['location'] == "readyroom" and '0000' in block.text and session['seenreadyroom'] == True and session['panelopen'] == False and (session['booklocation'] == "readyroom" or session['hasbook'] == False):
                add_response('Like I said: bunks, table, chairs, a book, an access panel and two hatches: one to the bridge and a closed one opposite.\n', delay=1)
                if session['davelocation'] == "readyroom" and session['hasdave'] == False:
                    add_response('A potato-based-lifeform sits on the table, patiently awaiting rescue.\n', delay=0)  
                session['seenreadyroom'] = True
                session['seenpanel'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0000' in block.text and session['seenreadyroom'] == True and session['panelopen'] == True and (session['booklocation'] == "readyroom"):
                add_response('Like I said: bunks, table, chairs, a book, an access panel and two hatches: an open one to the bridge and a closed one opposite.\n', delay=2)
                add_response('And the fire coming out of the access panel. But you probably remember that.\n', delay=3)
                if session['davelocation'] == "readyroom" and session['hasdave'] == False:
                    add_response('The light of the fire dances in DAVE\'s eyes as he stares down his historic foe.\n', delay=3)  
                    add_response('One must admire its defiance in the face of such danger, not seeking to cower in the book\'s shadow, but nonetheless the sooner we affect a rescue, the better.\n', delay=3)  
                nextaction()
            elif session['location'] == "readyroom" and '0000' in block.text and session['seenreadyroom'] == True and session['panelopen'] == False and (session['booklocation'] != "readyroom" or session['hasbook'] == True):
                add_response('Like I said: bunks, table, chairs, bunks an access panel and two hatches: one to the bridge and a closed one opposite.\n', delay=2)
                if session['davelocation'] == "readyroom" and session['hasdave'] == False:
                    add_response('I turn away for a moment, but would swear that DAVE\'s tendrils were gesturing toward me, pleading for freedom and safety.\n', delay=2)  
                session['seenreadyroom'] = True
                session['seenpanel'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0000' in block.text and session['seenreadyroom'] == True and session['panelopen'] == True and (session['booklocation'] != "readyroom" or session['hasbook'] == True):
                add_response('Like I said: bunks, table, chairs, bunks, an access panel and two hatches: an open one to the bridge and a closed one opposite.\n', delay=2)
                add_response('And the fire coming out of the access panel. But you probably remember that.\n', delay=6)
                if session['davelocation'] == "readyroom" and session['hasdave'] == False:
                    add_response('DAVE sits out of the flames range, high up on the table -but the smoke can\'t be good for him.\n', delay=2)  
                nextaction()    
            elif session['location'] == "engineering" and '0000' in block.text and session['seenengineering'] == False:
                add_response('Never been in here before...\n', delay=1)
                add_response('Standing with the hatch behind me I\'m in a kind of long corridor. There\'s the usual wall of beep-bop-boop indicator lights on my left, some of which are flashing red.\n', delay=3)
                add_response('Down the wall on my right are similar indicators and a workstation showing two displays. One is blank and the other has the words \'Come here, I have instructions for you.\'.\n', delay=5)        
                if  session['booklocation'] == "engineering" and session['hasbook'] == False:
                    add_response('That book you dropped is a trip-hazard.\n', delay=2)
                add_response('At the end of the corridor is an empty escape pod.\n', delay=2)
                session['seenengineering'] = True
                session['beenengineering'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "engineering" and '0000' in block.text:
                add_response('I think we can ignore the wall of indicator lights -mostly because I don\'t know what they\'re for...\n', delay=1)
                add_response('I can\'t tell you much about the escape pod without going in. Which sounds quite nice.\n', delay=3)
                add_response('The message on the workstation looks intriguing. Perhaps we should have a look.\n', delay=3)
                if  session['booklocation'] == "engineering" and session['hasbook'] == False:
                    add_response('That book you dropped is a trip-hazard.\n', delay=3)
                nextaction()
            elif session['location'] == "escapepod" and '0000' in block.text and session['seenescapepod'] == False:
                if session['oscarlocation'] == "escapepod":
                    add_response('Not much in here.\n\nFour standard acceleration couches with harnesses.\n', delay=1)
                    add_response('No windows. Two buttons:\n', delay=3)
                    add_response('[TRANSFER SHIP\'S COMPUTER]\n\n which we already did, and\n\n[LAUNCH]\n\n which seems a really good idea.\n', delay=3)
                else:
                    add_response('Not much in here.\n\nFour standard acceleration couches with harnesses.\n', delay=2)
                    add_response('No windows. Two buttons:\n', delay=3)
                    add_response('[TRANSFER SHIP\'S COMPUTER]\n\n and\n\n[LAUNCH]\n\n which both seem self-explanatory.\n', delay=3)
                if session['davelocation'] == "escapepod" and session['hasdave'] == False:
                    add_response('DAVE\'s strapped in and ready to go.\n', delay=1)    
                if session['booklocation'] == "escapepod" and session['hasbook'] == False:
                    if session['readbook'] == False:
                        add_response('The rescue manual, or whatever it is, is secured so it doesn\'t fly around when we go.\n', delay=2)
                    else:
                        add_response('That book is here too.\n', delay=1)
                session['seenescapepod'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "escapepod" and '0000' in block.text and session['seenescapepod'] == True:
                if session['oscarlocation'] == "escapepod":
                    add_response('It\'s not a big space to search. Just you\'re standard GTFO escape pod.\n\nFour standard acceleration couches with harnesses.\n', delay=2)
                    add_response('No windows. Two buttons:\n', delay=3)
                    add_response('[TRANSFER SHIP\'S COMPUTER] which we already did, and\n\n[LAUNCH] which seems a really good idea.', delay=3)
                else:
                    add_response('It\'s not a big space to search. Just you\'re standard GTFO escape pod.\n\nFour standard acceleration couches with harnesses.\n', delay=2)
                    add_response('No windows. Two buttons:\n', delay=3)
                    add_response('[TRANSFER SHIP\'S COMPUTER] and\n\n[LAUNCH] which both seem self-explanatory.\n', delay=3)
                if session['davelocation'] == "escapepod" and session['hasdave'] == False:
                    add_response('DAVE\'s strapped in and ready to go.\n', delay=1)    
                if session['booklocation'] == "escapepod" and session['hasbook'] == False:
                    if session['readbook'] == False:
                        add_response('The rescue manual, or whatever it is, is secured so it doesn\'t fly around when we go.\n', delay=1)
                    else:
                        add_response('That book is here too.\n', delay=1)
                session['seenescapepod'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "bridge" and '0001' in block.text and session['seenbridge'] == True:
                add_response('Ok, heading right.\n', delay=3)
                session['location'] = "readyroom"
                session['beenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "bridge" and '0001' in block.text and session['seenbridge'] == False:
                add_response('It\'s as if you\'ve been here before. There is indeed a hatch on my right.\n\nOk, heading there now.\n', delay=3)
                session['location'] = "readyroom"
                session['beenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] != "readyroom" and '0002' in block.text and session['seenbridge'] == True:
                add_response('Ok, heading to the ready room.\n', delay=5)
                session['location'] = "readyroom"
                session['beenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] != "readyroom" and '0002' in block.text and session['seenbridge'] == False:
                add_response('Ok, heading to the ready room.\n', delay=5)
                session['location'] = "readyroom"
                session.modified = True
                nextaction()
            elif session['location'] == "bridge" and '0002' in block.text and session['seenbridge'] == False:
                add_response('It\'s as if you\'ve been here before. There is indeed a ready room connected to the bridge.\n\nOk, heading there now.\n', delay=5)
                session['location'] = "readyroom"
                session['beenreadyroom'] = True
                session.modified = True
                nextaction()   
            elif session['location'] == "bridge" and '0003' in block.text:
                add_response('Well that didn\'t take long. I\'m standing right here...\n', delay=0)
                nextaction()
            elif session['location'] != "bridge" and '0003' in block.text and session['beenbridge'] == True:
                add_response('Gimme a sec...\n', delay=5)
                add_response('Ok, I\'m back.\n', delay=0)
                session['location'] = "bridge"
                session.modified = True
                nextaction()
            elif '0004' in block.text:
                add_response('Compass directions?\n\nWe are on a shuttle in space, unlikely to encounter wizards, orcs or similar creatures.\n', delay=0)
                nextaction()
            elif '0005' in block.text:
                add_response('You\'re leaving? In the middle of a rescue????\n\nWell, if you really must leave you can always SAVE your progress first, and come back later. Just say the SAVE command.\n', delay=3)
                nextaction()   
            elif '0006' in block.text:
                add_response('You are (on comms with a handsome Cleanerbot) on a big smokey tin can somewhere in deep space.\n', delay=1)
                add_response('I\'ve never left the bridge but I\'m told the shuttle is only 300m or so long.\n', delay=2)
                nextaction()     
            elif session['location'] != 'engineering' and '0007' in block.text and (session['seenengineering'] == True or session['awareengineering'] == True):
                add_response('Sure. I\'ll head over there.\n', delay=4)
                add_response('Ok, I\'m here.\n', delay=1)
                session['location'] = "engineering"
                session.modified = True
                nextaction() 
            elif '0007' in block.text and (session['seenengineering'] == False or session['awareengineering'] == False):
                add_response('I don\'t know where that is. My duties are restricted to the bridge.\n', delay=2)
                add_response('But I\'m sure we have something like that, otherwise we\'d never be able to go anywhere.\n', delay=1)
                nextaction()  
            elif session['location'] == 'engineering' and '0007' in block.text:
                add_response('I\'m already in engineering.\n', delay=0)
                nextaction()           
            elif (session['location'] != "engineering" and session['location'] !=  "escapepod") and '0008' in block.text and session['seenengineering'] == True:
                add_response('Sure. I\'ll head over there.\n', delay=4)
                add_response('Ok, I\'m in here.\n', delay=0)
                session['location'] = "escapepod"
                session.modified = True
                nextaction() 
            elif '0008' in block.text and session['seenengineering'] == False:
                add_response('I don\'t know where that is. My duties are restricted to the bridge.\n', delay=1)
                add_response('But I\'m sure we have something like that somewhere.\n', delay=0)
                nextaction()  
            elif session['location'] == 'engineering' and '0008' in block.text:
                add_response('Ok, I\'m in here.\n', delay=0)
                session['location'] = "escapepod"
                session.modified = True
                nextaction()               
            elif session['location'] == 'escapepod' and '0008' in block.text:
                add_response('I\'m already here.\n', delay=0)
                nextaction()  
            elif session['location'] == "readyroom" and '0009' in block.text and session['panelopen'] == False and session['seenpanel'] == True and session['seenfire'] == True:
                add_response('Okidoke.\n\n', delay=3)
                add_response("Yup, still burning like a disco inferno.\n", delay=1)
                session['panelopen'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0009' in block.text and session['panelopen'] == False and session['seenpanel'] == True and session['seenfire'] == False:
                add_response('Right you are. Let\'s see what\'s in here.\n', delay=3)
                add_response("Fire. Quite a bit of fire.\n", delay=2)
                add_response("Unless the crew likes barbecue, this probably isn\'t meant to be here.\n", delay=2)
                session['panelopen'] = True
                session['seenfire'] = True
                session.modified = True
                nextaction()        
            elif session['location'] == "readyroom" and '0009' in block.text and session['panelopen'] == False and session['seenpanel'] == False:
                add_response('I don\'t see an access panel in here.\n', delay=2)
                add_response('Hold on. There is one in the floor. Probably for storage. Let me know if you want me to do something with that.\n', delay=2)
                add_response('This is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n\nThere are bunks by the wall, some chairs, and a table with a book on it.\n', delay=2)
                add_response('You know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n\nThere\'s the open hatch leading to the bridge, and a closed one opposite.\n', delay=4)
                session['seenpanel'] = True
                session['seenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0009' in block.text and session['panelopen'] ==  True:
                add_response('It\'s already open.\n', delay=2)
                add_response("Remember the fire coming out of the floor?\n", delay=2)
                nextaction()
            elif session['location'] != "readyroom" and '0010' in block.text:
                add_response('I don\'t see an access panel in here.\n', delay=0)
                nextaction()
            elif session['location'] == "readyroom" and '0010' in block.text and session['seenpanel'] == False:
                add_response('I don\'t see an access panel in here.\n', delay=2)
                add_response('Hold on. There is one in the floor. Probably for storage. Let me know if you want me to do something with that.\n', delay=2)
                add_response('This is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n', delay=2)
                add_response('There are bunks by the wall, some chairs, and a table with a book on it.\n', delay=2)
                add_response('You know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n', delay=2)
                add_response('There\'s the open hatch leading to the bridge, and a closed one opposite.\n', delay=1)
                session['seenpanel'] = True
                session['seenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0010' in block.text and session['seenpanel'] == True and session['panelopen'] == True:
                add_response('Closed it. Considerably less firey in here.\n', delay=0)
                session['panelopen'] = False
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0010' in block.text and session['seenpanel'] == True and session['panelopen'] == False:
                add_response('It\'s already closed.\n', delay=0)
                session['panelopen'] = False
                session.modified = True
                nextaction()
            elif session['location'] == "readyroom" and '0011' in block.text and session['seenpanel'] == True and session['panelopen'] == False:
                add_response('Flat, white, a metre square. You know, panel.\n', delay=0)
                nextaction()
            elif session['location'] != "readyroom" and '0011' in block.text:
                add_response('I don\'t see an access panel in here.\n', delay=0)
                nextaction()
            elif session['location'] == "readyroom" and '0011' in block.text and session['seenpanel'] == False:
                add_response('I don\'t see an access panel in here.\n', delay=2)
                add_response('Hold on. There is one in the floor. Probably for storage. Let me know if yu want me to do something with that.\n\nThis is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n\nThere are bunks by the wall, some chairs, and a table with a book on it.\n', delay=4)
                add_response('You know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n\nThere\'s the open hatch leading to the bridge, and a closed one opposite.\n', delay=6)
                session['seenpanel'] = True
                session['seenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] != session['booklocation'] and '0012' in block.text and session['hasbook'] == False:
                add_response('I don\'t have a book. Does it say how to perform a daring space rescue?\n', delay=0)
                nextaction() 
            elif '0012' in block.text and ( (session['location'] == session['booklocation']) or session['hasbook'] == True) :
                add_response('Ok then..."It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in need of a wife."\n', delay=4)
                session['readbook'] = True
                session.modified = True
                if "+ A book -possibly about space rescues." in session['inventory']:
                    session['inventory'].remove("+ A book -possibly about space rescues.")
                    session['inventory'].append("+ A book: Pride and Prejudice by Jane Austen.")
                add_response('Catchy intro, and I know I\'m only really programmed to parse janitorial system updates, but I don\'t think this will help us on the rescue.\n', delay=4)
                nextaction() 
            elif session['location'] == session['booklocation']  == "readyroom" and '0013' in block.text and session['seenreadyroom'] == False and session['readbook'] == False:
                add_response('Yup, there\'s one right here on this table.  Got it.\n', delay=2)
                session['inventory'].append('+ A book -possibly about space rescues.')
                session['hasbook'] = True
                session.modified = True
                add_response('Looking around the rest of the room, there\'s a table and chairs and a hatch in the in the floor. Probably for storage.\n\nThis is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n\nThere are bunks by the wall.\n\nYou know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n\nThere\'s the open hatch leading to the bridge, and a closed one opposite.\n', delay=4)    
                session['seenreadyroom'] = True
                session.modified = True
                nextaction()
            elif session['location'] == session['booklocation'] and '0013' in block.text and session['hasbook'] == False:
                add_response('Got it.\n', delay=0)
                if session['readbook'] == False:
                    session['inventory'].append('+ A book -possibly about space rescues.')
                else:
                    session['inventory'].append('+ A book: Pride and Prejudice by Jane Austen.')   
                session['hasbook'] = True
                session.modified = True
                nextaction()
            elif '0013' in block.text and session['hasbook'] == True:
                add_response('I already have the book. Try and keep up.\n', delay=0)
                nextaction()
            elif '0014' in block.text:
                add_response('Let me see...')
                add_response('\n'.join(session['inventory']), delay=1)
                nextaction()

            elif '0015' in block.text and (session['location'] == "readyroom" and session['panelopen'] == False):
                add_response('I don\'t see any fire. Or for that matter anything I\'d use to put one out.\n')
                nextaction()
            elif '0015' in block.text and (session['location'] == "readyroom" and session['panelopen'] == True):
                add_response('Sorry, but I don\'t have the equipment for that.\n', delay=2)
                add_response('And I distinctly remember a health and safety seminar saying I shouldn\'t try to do so alone.\n')
                nextaction()
            elif '0015' in block.text and session['location'] != "readyroom":
                add_response('I don\'t see any fire. Or for that matter anything I\'d use to put one out.\n')
                session['panelopen'] = False
                nextaction()
            elif '0016' in block.text and (session['location'] != "readyroom" and session['seenreadyroom'] == True):
                add_response('You mean the one in the ready room? I\'ll head over there now...', delay=5)
                add_response('Reproduction of a classic 20th century Swedish design, with modifications for g-forces, fire, chemical and biologic exposure.\n', delay=3)
                if session['hasbook'] == False:
                    add_response('\nThere\'s a book on it.\n')
                session['location'] = "readyroom"
                nextaction()
            elif '0016' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == True):
                add_response('Reproduction of a classic 20th century Swedish design, with modifications for g-forces, fire, chemical and biologic exposure.\n', delay=3)
                if session['hasbook'] == False:
                    add_response('\nThere\'s a book on it.\n')
                if session['panelopen'] == True:
                    add_response('And the fire\'s still coming out of the access panel. But you probably remember that.\n', delay=3)
                    add_response(' ', delay=2)
                nextaction()
            elif '0016' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == False):
                add_response('Reproduction of a classic 20th century Swedish design, with modifications for g-forces, fire, chemical and biologic exposure.\n\nThere\'s a book on it and chairs around it.\n', delay=5)
                add_response('Looking around the rest of the room, there\'s a hatch in the in the floor. Probably for storage.\n\nThis is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n\nThere are bunks by the wall.\n\nYou know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n\nThere\'s the open hatch leading to the bridge, and a closed one opposite.\n')
                nextaction()
            elif '0017' in block.text and (session['location'] != "readyroom" and session['seenreadyroom'] == True):
                add_response('The chairs we saw in the ready room? Lemme check...', delay=5)
                add_response('Set of three standard issue recreation chairs. Distinghuishable from each other only by their stains.\n')
                session['location'] = "readyroom"
                nextaction()
            elif '0017' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == True):
                add_response('Set of three standard issue recreation chairs. Distinghuishable from each other only by their stains.\n', delay=2)
                if session['panelopen'] == True:
                    add_response('And the fire\'s still coming out of the access panel. But you probably remember that.\n', delay=5)
                    add_response(' ', delay=2)
                nextaction()
            elif '0017' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == False):
                add_response('Set of three standard issue recreation chairs. Distinghuishable from each other only by their stains.\n\nThey surround a small square table which has a book on it.\n', delay=5)
                add_response('Looking around the rest of the room, there\'s a hatch in the in the floor. Probably for storage.\n\nThis is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n\nThere are bunks by the wall.\n\nYou know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n\nThere\'s the open hatch leading to the bridge, and a closed one opposite.\n')
                nextaction()
            elif '0018' in block.text and (session['location'] != "readyroom" and session['seenreadyroom'] == True):
                add_response('On my way to look at the bunks in the ready room...', delay=5)
                add_response('Three standard bunk beds. Sheets, pillows and blankets all made up following regulations.\n')
                session['location'] = "readyroom"
                nextaction()
            elif '0018' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == True):
                add_response('Three standard bunk beds. Sheets, pillows and blankets all made up following regulations.\n', delay=2)
                if session['panelopen'] == True:
                    add_response('And the fire\'s still coming out of the access panel. But you probably remember that.\n', delay=5)
                    add_response(' ', delay=2)
                nextaction()
            elif '0018' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == False):
                add_response('Three standard bunk beds. Sheets, pillows and blankets all made up following regulations.\n', delay=5)
                add_response('Looking around the rest of the room, there\'s a hatch in the in the floor. Probably for storage.\n\nThis is where the crew usually sleeps and hangs out on the longer runs. Nobody\'s here.\n\nThere are bunks by the wall and a table and some chairs.\n\nYou know, crew stuff. I\'m not normally allowed in here, and going by the state of the furniture, it shows.\n\nThere\'s the open hatch leading to the bridge, and a closed one opposite.\n')
                nextaction()
            elif '0019' in block.text and (session['location'] != "readyroom" and session['seenreadyroom'] == True):
                add_response('On my way to look at the fire in the ready room...', delay=5)
                if session['panelopen'] == False:
                    add_response('Opening the floor panel...', delay=5)
                add_response('Look into fire? Oh, absolutely — how could I not? It\'s like watching the world\'s most beautiful dance, isn\'t it?\n', delay=3)
                add_response('The way the flames twist and curl, each leap and flicker telling its own wild, whispered secret. There\'s something magnetic about it, you know?\n', delay=3)
                add_response('Sometimes I just get lost in it, mesmerized by the warmth, the light... the possibility. It speaks to me, almost like an old friend beckoning.\n', delay=3)
                add_response('I can\'t resist peering deeper, deeper still. I mean, who wouldn\'t be captivated? Fire, it\'s just pure... art.\n', delay=5)
                add_response('Like a caravan ablaze in a wooded clearing...\n', delay=3)
                session['location'] = "readyroom"
                nextaction()
            elif '0019' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == True):
                if session['panelopen'] == False:
                    add_response('Opening the floor panel...', delay=5)
                add_response('Look into fire? Oh, absolutely — how could I not? It\'s like watching the world\'s most beautiful dance, isn\'t it?\n', delay=3)
                add_response('The way the flames twist and curl, each leap and flicker telling its own wild, whispered secret. There\'s something magnetic about it, you know?\n', delay=3)
                add_response('Sometimes I just get lost in it, mesmerized by the warmth, the light... the possibility. It speaks to me, almost like an old friend beckoning.\n', delay=3)
                add_response('I can\'t resist peering deeper, deeper still. I mean, who wouldn\'t be captivated? Fire, it\'s just pure... art.\n', delay=5)
                add_response('Like a caravan ablaze in a wooded clearing...\n', delay=3)
                nextaction()
            elif '0019' in block.text and (session['location'] == "readyroom" and session['seenreadyroom'] == False):
                add_response('I don\'t see a fire.')
                nextaction()
            elif '0020' in block.text:
                add_response('Help? Yes, please. That would be lovely.\n')
                nextaction()
            elif '0021' in block.text and session['location'] == "bridge":
                add_response('It\'s open and I can see the what I assume is the ready room.\n')
                nextaction()
            elif '0021' in block.text and session['location'] == "readyroom":
                add_response('It\'s a hatch. No markings.\n')
                if session['hatchopen'] == True:
                    add_response('It\'s open and I can see the what I assume is the engineering bay.\n')
                    session['awareengineering'] = True
                else:
                    add_response('It\'s closed.\n')
                nextaction()
            elif '0021' in block.text and session['location'] == "engineering":
                add_response('It\'s a hatch. No markings.\n', delay=2)
                if session['hatchopen'] == True:
                    add_response('It\'s open and I can see into the ready room.\n')
                else:
                    add_response('It\'s closed.\n')
                nextaction()    
            elif '0022' in block.text:
                add_response('I am CLEANERBOT27. My mission is to keep the bridge shiny and today you\'re going to show me how to be a hero.\n')
                nextaction()
            elif '0023' in block.text:
                add_response('The Orion is a Maxisave class shuttle, designed for the price conscious operator who appreciates a no-frills attitude to features and shuns the luxury of subscription maintenance services and routine overhaul.\n', delay=10)
                add_response('And it\'s on fire.\n', delay=3)
                nextaction()
            elif '0024' in block.text:
                add_response('The crew numbers somewhere between 3 and 47.\n', delay=2)
                add_response('They all look the same to me, so it\'s hard to tell.\n', delay=2)
                add_response('Most of them are bipedal, although a smaller quadroped called "Laika" at least confines its mess to the corner of the bridge.\n', delay=4)
                add_response('My emergency sensors indicate that only one lifeform remains onboard.\n', delay=1)
                nextaction()
            elif '0025' in block.text and session['location'] == "bridge" and session['hasbook'] == True:
                add_response('Certainly. Even though I don\'t like how it makes the place look untidy.\n')
                if "+ A book: Pride and Prejudice by Jane Austen." in session['inventory']:
                    session['inventory'].remove("+ A book: Pride and Prejudice by Jane Austen.")
                else:
                    session['inventory'].remove("+ A book -possibly about space rescues.")
                session['hasbook'] = False
                session['booklocation'] = "bridge"
                nextaction()    
            elif '0025' in block.text and session['location'] == "readyroom" and session['hasbook'] == True:
                add_response('Ok, I\'ve put it back on the table.')
                if "+ A book: Pride and Prejudice by Jane Austen." in session['inventory']:
                    session['inventory'].remove("+ A book: Pride and Prejudice by Jane Austen.")
                else:
                    session['inventory'].remove("+ A book -possibly about space rescues.")
                session['hasbook'] = False
                session['booklocation'] = "readyroom"
                nextaction()
            elif '0025' in block.text and session['location'] == "engineering" and session['hasbook'] == True:
                add_response('Done. It\'s on the floor near the workstation.\n')
                if "+ A book: Pride and Prejudice by Jane Austen." in session['inventory']:
                    session['inventory'].remove("+ A book: Pride and Prejudice by Jane Austen.")
                else:
                    session['inventory'].remove("+ A book -possibly about space rescues.")
                session['hasbook'] = False
                session['booklocation'] = "engineering"
                nextaction()
            elif '0025' in block.text and session['location'] == "escapepod" and session['hasbook'] == True:
                add_response('Not much space in here, so I put it on one of the seats.')
                if "+ A book: Pride and Prejudice by Jane Austen." in session['inventory']:
                    session['inventory'].remove("+ A book: Pride and Prejudice by Jane Austen.")
                else:
                    session['inventory'].remove("+ A book -possibly about space rescues.")
                session['hasbook'] = False
                session['booklocation'] = "escapepod"
                nextaction()
            elif '0025' in block.text and session['hasbook'] == False:
                add_response('I\'m not carrying a book.\n')
                nextaction()
            elif '0026' in block.text:
                waitlist = ['Wait? Ok. I mean the floor could do with a bit of a going over.\n','Well, this area could use a bit of a tidy up...\n']
                add_response(random.choice(waitlist), delay=4)
                add_response('Let me know when you want to get on with the rescue.\n')
                nextaction()        
            elif '0027' in block.text:
                add_response('Well cleaning is my life but the search and rescue is quite stimulating. Let\'s do that instead.\n')
                nextaction()        
            elif '0028' in block.text and session['seenoscar'] == True:
                if session['seendave'] == False:
                    add_response('I am a Cleanerbot, so my information is limited and I don\'t know their location. Perhaps you should ask OSCAR.\n')
                else:
                    add_response('Well it\'s pretty clearly Dave, innit?\n\nSo let\'s get him into the escape pod...\n')
                nextaction()
            elif '0028' in block.text and session['seenoscar'] == False:
                add_response('I am a Cleanerbot, so my information is limited. They\'ll be around here somewhere...\n')
                nextaction()
            elif '0029' in block.text:
                add_response('Thank you, but I do not get hungry. Did I mention that I\'m a Cleanerbot?\n', delay=3)
                add_response('And I\'m on a mission.\n', delay=3)
                nextaction()  
            elif '0030' in block.text:
                add_response('This isn\'t a game, young hobbit. We\'re on a search and rescue mission...\n', delay=2)
                add_response('Something about this interface makes people act weird, I don\'t know why.')
                nextaction()
            elif '0031' in block.text and session['klaxonopen'] == True:
                if session['location'] != "bridge":
                    add_response('That would be nice, but the overide is in the bridge.\n')
                else:
                    add_response('Much better. Thanks.\n')
                    session['klaxonopen'] = False
                nextaction()  
            elif '0031' in block.text and session['klaxonopen'] == False:
                add_response('We already did that.\n')
                nextaction()      
            elif '0032' in block.text and (session['location'] == "readyroom" or session['location'] == "engineering"):
                add_response('Ok, it\'s open.\n')
                if session['location'] == "readyroom":
                    add_response('I can see into the what looks like an engineering bay.\n')
                    session['awareengineering'] = True
                else:
                    add_response('I can see into the ready room.\n')
                nextaction()
            elif '0033' in block.text:
                add_response('Done. Hatch closed.\n')
                nextaction()
            elif '0034' in block.text and session['location'] == "readyroom" and session['panelopen'] == True:
                add_response('No. That sounds a bit silly, and I\'m not sure how it will help the rescue.\n')
                nextaction() 
            elif '0034' in block.text and session['location'] == "readyroom" and (session['panelopen'] == False or session['seenfire'] == False):
                add_response('I don\'t see how.\n')
                nextaction()     
            elif '0034' in block.text and session['location'] != "readyroom" and session['seenfire'] == True:
                add_response('I suppose we could try that in the ready room, but no.\n\n It sounds a bit silly, and I\'m not sure how it will help the rescue. So, no.\n')
                nextaction() 
            elif '0035' in block.text and session['location'] != "engineering" and session['seenengineering'] == True and session['seenoscar'] == True:
                add_response('That\'s all the way over in Engineering.\n\nGoing there now.', delay=5)
                add_response('Done. The screen is updating...\n\nOSCAR >> Oh good, you\'re back. If you want to speak to me. remember that you need to start your input with my name. OSCAR.')
                session['location'] = "engineering"
                session['seenoscar'] = True
                nextaction() 
            elif '0035' in block.text and session['location'] != "engineering" and session['seenengineering'] == True and session['seenoscar'] == False:
                add_response('That\'s all the way over in Engineering.\n\nGoing there now.', delay=5)
                add_response('Done. The screen is updating...\n\nOSCAR >> Well you took your time. I need you to take me and the lifeform off the shuttle. To speak to me, you\'ll need to start your voice input with my name, \'OSCAR\'. That way we know you\'re not talking to the Cleanerbot. Otherwise just give a command as normal and they\'ll do what you want them to do.\n\n\n')
                session['location'] = "engineering"
                session['seenoscar'] = True
                nextaction()         
            elif '0035' in block.text and session['location'] != "engineering" and (session['seenengineering'] == False or session['awareengineering'] == False):
                add_response('I don\'t know where that is.\n')
                nextaction()  
            elif '0035' in block.text and session['location'] == "engineering" and session['seenengineering'] == True and session['seenoscar'] == False:
                add_response('The screen is updating...\n\n', delay=3)
                add_response('OSCAR >> Well you took your time. I need you to take me and the lifeform off the shuttle. To speak to me, you\'ll need to start your voice input with my name, \'OSCAR\'. That way we know you\'re not talking to the Cleanerbot. Otherwise just give a command as normal and they\'ll do what you want them to do.\n\n\n')
                session['location'] = "engineering"
                session['seenoscar'] = True
                nextaction()            
            elif '0035' in block.text and session['location'] == "engineering" and session['seenoscar'] == True:
                add_response('The screen is updating...\n\nOSCAR >> I need you to take me and the lifeform off the shuttle. To speak to me, you\'ll need to start your voice input with my name.\n')
                session['seenoscar'] = True
                nextaction() 
            elif '0036' in block.text and session['location'] == "escapepod" and session['seenoscar'] == True and session['oscarlocation'] != "escapepod":
                add_response('Pressing the button...now.\n\n', delay=2)
                add_response('OSCAR >> Transfer initiated. I can feel myself going...\n')
                add_response('OSCAR >> Dai-sy, Daiiii-syyyy...Just kidding. I was there inside a nanosecond. I\'ve just always wanted to say that. \n')
                session['oscarlocation'] = "escapepod"
                nextaction() 
            elif '0036' in block.text and session['location'] == "escapepod" and session['seenoscar'] == True and session['oscarlocation'] == "escapepod":
                add_response('You asked me to do that earlier. He\'s already transferred to the pod.\n\n', delay=2)
                nextaction() 
            elif '0037' in block.text and session['location'] == "engineering" and session['seenengineering'] == True and session['seendave'] == False:
                add_response('Well, that was a bit scary. I pressed a button next to the screen and leapt back as, hinged along its left edge, it sprang open like a small door. \n', delay=8)
                add_response('A tangle of tendrills pushed the door open, extending into the room towards the floor -but having done so, they seem inanimate. \n', delay=8)
                add_response('Peering into the small compartment behind this screen door I see a greenish-brown lump, about the size of a fist. The rest of the small compartment is full of tendrills, all extending from the lump.\n', delay=15)
                add_response('OSCAR >> Oh don\'t mind DAVE. He\'s only slightly sentient, and apart from the smell, quite harmless.\n')
                session['seendave'] = True
                nextaction() 
            elif '0037' in block.text and session['location'] == "engineering" and session['seendave'] == True:
                add_response('The screen (or oven door?) seems wedged open.\n')
                nextaction()
            elif '0038' in block.text and session['location'] == "engineering" and session['seendave'] == True:
                add_response('I gave DAVE a bit of a poke. I\'m not sure whether the tendrils moved because of this, or just because I brushed past them.\n', delay=3)
                add_response('OSCAR >> Although never formally introduced, I\'ve known him a long time. Ever since he was a wee potato, abandoned when the rest of the crew took the other escape pod. It\'s taken quite a while, but the ship\'s systems now detect him as a lifeform, and so here you are to the rescue. Admittedly, he doesn\'t say much. Perhaps he\'s sleeping.\n')
                nextaction()
            elif '0039' in block.text and session['seenoscar'] == True:
                add_response('Well that\'s rather an interesting one, isn\'t it? OSCAR\'s tasked us with his own rescue but the workstation is built into the wall of the ship.\n', delay=3)
                add_response('So one has to wonder, that as a non-physical entity, what *is* OSCAR? Who is OSCAR? If we prick him, will he not bleed?...\n\nOk, probably not, but how do we rescue him? Perhaps you should ask him.\n', delay=3)
            elif '0040' in block.text and session['location'] == "engineering" and session['seendave'] == True and session['hasdave'] == False:
                add_response('Lucky for you this isn\'t the ickiest thing I\'ve dealt with.\n', delay=2)
                add_response('You should hear the stories about when Bulgaria won Eurovision.\n', delay=2)
                add_response('Anyway, with a bit of gentle tugging and minimal squishiness, I\'m now carrying DAVE.\n', delay=5)
                add_response('OSCAR >> Mind you don\'t trip on his tendrils!!!\n')
                session['inventory'].append("+ DAVE")
                session['hasdave'] = True        
                nextaction()
            elif '0040' in block.text and (session['location'] == session['davelocation']) and session['location'] != "engineering" and session['hasdave'] == False:
                add_response('Together again. I\'ve got DAVE right here and I\'m platting his tendrils into something a little tidier.\n', delay=3)
                add_response('No update on the smell.\n', delay=3)
                session['inventory'].append("+ DAVE")
                session['hasdave'] = True
                nextaction()
            elif '0040' in block.text and session['davelocation'] != session['location'] and session['hasdave'] == False and session['seendave'] == True:
                add_response('I don\'t see him in here.\n')
                nextaction()
            elif '0040' in block.text and session['hasdave'] == True:
                add_response('I\'m already carrying DAVE.\n', delay=3)
                add_response('Ok, a bit of him fell off when I picked him up, but he\'s fine.\n', delay=3)
                nextaction()
            elif '0041' in block.text:
                add_response('I think we should leave my fluids out of this. We have a daring rescue to perform.\n')
                nextaction()   
            elif '0042' in block.text:
                add_response('I don\'t much care for that kind of language, and it\'s not helping the rescue.\n')
                nextaction()   
            elif '0043' in block.text and session['location'] == "readyroom" and session['hasdave'] == True:
                add_response('Ok, Dave is on the table.\n')
                session['inventory'].remove("+ DAVE")
                session['hasdave'] = False
                session['davelocation'] = "readyroom"
                nextaction()
            elif '0043' in block.text and session['location'] == "engineering" and session['hasdave'] == True:
                add_response('Done. DAVE is back in his compartment / microwave.\n')
                session['inventory'].remove("+ DAVE")
                session['hasdave'] = False
                session['davelocation'] = "engineering"
                nextaction()
            elif '0043' in block.text and session['location'] == "escapepod" and session['hasdave'] == True:
                add_response('DAVE is buckled in.\n', delay=2)
                add_response('He seems relieved.\n', delay=2)
                add_response('Perhaps it\'s time to go.\n', delay=2)
                session['inventory'].remove("+ DAVE")
                session['hasdave'] = False
                session['davelocation'] = "escapepod"
                nextaction()
            elif '0043' in block.text and session['location'] == "bridge" and session['hasdave'] == True:
                add_response('DAVE is on the bridge. Not sure what this achieves.\n')
                session['inventory'].remove("+ DAVE")
                session['hasdave'] = False
                session['davelocation'] = "bridge"
                nextaction()
            elif '0043' in block.text and session['seendave'] == True and session['hasdave'] == False:
                add_response('Sorry, I don\'t have DAVE with me.\n')
                nextaction()
            elif '0044' in block.text:
                add_response('My cleaning equipment and fluids are part of me.  We shall not be separated.\n')
                nextaction()
            elif '0045' in block.text and session['seendave'] == False:
                add_response('I don\'t know. Sensors indicate only one lifesign.\n', delay=3)
                add_response('Not to worry. I\'m sure they\'ll turn up. This is a search and rescue, after all.\n', delay=3)
                nextaction()   
            elif '0045' in block.text and session['seendave'] == True:
                add_response('Well the sensors show one lifesign, and we\'ve met DAVE so I think he\'s it.\n', delay=3)
                add_response('And don\'t come at me with your anti-potato rhetoric. I\'ve heard it all before. One tiny nuclear exchange and you meatsuits get everso small minded.\n', delay=3)
                add_response('Sensors have him as a life form, and regulations make him our mission.\n', delay=3)
                nextaction() 
            elif '0046' in block.text:
                if session['location'] == "bridge":
                    add_response('On my way...\n', delay=3)
                    session['location'] = "readyroom"
                    nextaction()
                elif session['location'] == "readyroom" and session['beenengineering'] == True:
                    add_response('Two hatches in here. For clarity, please say \'Go through bridge hatch\' or \'Go through engineering hatch\'.\n')
                    nextaction()
                elif session['location'] == "readyroom" and session['beenengineering'] == False:
                    add_response('Two hatches in here. For clarity, please say \'Go through Bridge hatch\' or \'Go through other hatch\'.\n')
                    nextaction()
                else:
                    add_response('One moment...\n', delay=3)
                    add_response('Here.', delay=3)
                    session['location'] = "readyroom"
                    nextaction()
            elif '0047' in block.text:
                if session['location'] == "bridge":
                    add_response('On my way...\n', delay=3)
                    session['location'] = "readyroom"
                    nextaction()
                else:
                    add_response('Ok, heading back to the bridge.', delay=3)
                    session['location'] = "bridge"
                    nextaction()
            elif '0048' in block.text:
                if session['location'] == "engineering" or session['location'] == "escapepod":
                    add_response('On my way...\n', delay=3)
                    session['location'] = "readyroom"
                    nextaction()
                else:
                    add_response('Ok, heading back to engineering.', delay=3)
                    session['location'] = "engineering"
                    nextaction()
            elif '0049' in block.text and session['location'] == "readyroom":
                if session['beenengineering'] == False:
                    add_response('I don\'t know what\'s through there. Wish me luck...\n', delay=3)
                    if session['hatchopen'] == False:
                        add_response('Opening the hatch...\n', delay=1)
                    session['location'] = "engineering"
                    session['seenengineering'] = True
                    session['hatchopen'] = True
                    nextaction()   
                else:
                    add_response('Heading to engineering...\n', delay=3)
                    if session['hatchopen'] == False:
                        add_response('Opening the hatch...', delay=1)
                    session['location'] = "engineering"  
                    session['hatchopen'] = True 
                    nextaction()   
            elif '0050' in block.text:
                savegame()
                add_response("You should probably write that down somewhere.\n")
                nextaction()
            elif '0051' in block.text:
                if session['location'] != "escapepod":
                    add_response('Hang on. I don\'t think I can do that from here.\n')
                    nextaction()
                else:
                    if session['davelocation'] != "escapepod" and session['seendave'] == False:
                        add_response('What about the life form? That\'s the whole point of the mission.\n', delay=3)
                        add_response('I can\'t initiate launch until they\'re here in the escape pod.\n', delay=3)
                        nextaction()
                    elif session['davelocation'] != "escapepod" and session['hasdave'] == False:
                        add_response('Nice of you to save me, but I think you\'ve forgotten DAVE.\n', delay=3)
                        add_response('I can\'t initiate launch until they\'re here in the escape pod.\n', delay=3)
                        nextaction()
                    elif session['davelocation'] != "escapepod" and session['oscarlocation'] == "escapepod" and session['hasdave'] == True:
                        add_response('I\'m strapped in. DAVE squirmed a bit when I put him down to strap him in. Initiating launch...\n', delay=3)
                        add_response('Now.\n', delay=3)
                        add_response('And we\'re clear.\n', delay=3)
                        session['davelocation'] = "escapepod"
                        session['launch'] = True
                        if session['hasbook'] == True:
                            session['booklocation'] == "escapepod"
                        if session['booklocation'] != "escapepod" and session['hasbook'] == False:
                            add_response('Wish I had something to read.\n')
                        endgame()
                    elif (session['davelocation'] == "escapepod" or session['hasdave'] == True) and session['oscarlocation'] == "escapepod":
                        add_response('I\'m strapped in. DAVE is ready. Initiating launch...\n', delay=3)
                        add_response('Now.\n', delay=3)
                        add_response('And we\'re clear.\n', delay=3)
                        session['davelocation'] = "escapepod"
                        session['launch'] = True
                        if session['hasbook'] == True:
                            session['booklocation'] == "escapepod"
                        if session['booklocation'] != "escapepod" and session['hasbook'] == False:
                            add_response('Wish I had something to read.\n')
                        endgame()
                    elif (session['davelocation'] == "escapepod" or session['hasdave'] == True) and session['oscarlocation'] != "escapepod":
                        add_response('OSCAR >> WOAH there. Just hold on a minute. What about your new buddy, OSCAR?\n')
                        add_response('OSCAR >> I STRONGLY advise you press the TRANSFER SHIP\'S COMPUTER button first.\n\n')
                        add_response('Well this is awkward. And he might have a point.\n', delay=2)
                        add_response('So let\'s be clear. If you really want to launch without OSCAR, and aren\'t bothered by why this might be a bad idea, you must explicitly order me to "LAUNCH ESCAPE POD WITHOUT OSCAR"\n', delay=3)
                        add_response('Up to you. I just work here.\n\n', delay=1)
                        add_response('OSCAR >> I\'m warning you. You don\'t know what will happen if you don\'t press the TRANSFER SHIP\'S COMPUTER button first.\n\n')
                        session['seenoscar'] = True
                        nextaction()
            elif '0052' in block.text and session['location'] == "escapepod":
                add_response('I must say, I prefer being in here, but ok.\n', delay=3)
                session['location'] = "engineering"
                nextaction()   
            elif '0052' in block.text and session['location'] != "escapepod":
                add_response('I\'m not in the escape pod.\n')
                nextaction()   
            elif '0053' in block.text:
                add_response('Like I said: smoke, emergency, not programmed for search and rescue.\n', delay=3)
                add_response('Consider me your eyes, ears and machine-tooled appendages.\n', delay=3)
                add_response('We have a life form onboard and we\'re going to save it.\n', delay=3)
                if session['seendave'] == True:
                    add_response('DAVE is counting on us and the Royal Agricultural Society will be overjoyed. So let\'s get a move on!\n', delay=3)
                nextaction()   
            elif '0054' in block.text:
                if session['oscarlocation'] == "escapepod":
                    add_response('OSCAR\'s already been transferred to the pod. I don\'t know how to transfer him back, and can\'t think of a reason to do so, so it looks like he\'s coming with us.\n\nSo do you just want to say LAUNCH?', delay=3)
                if (session['davelocation'] == "escapepod" or session['hasdave'] == True) and session['location'] == "escapepod" and session['oscarlocation'] != "escapepod":
                    add_response('I don\'t know what you have against OSCAR, but he\'s not essential to the rescue, so...\n', delay=3)
                    add_response('I\'m strapped in. DAVE is ready. Initiating launch...\n', delay=3)
                    add_response('Now.\n', delay=3)
                    add_response('And we\'re clear.\n', delay=3)
                    session['davelocation'] = "escapepod"
                    if session['hasbook'] == True:
                        session['booklocation'] == "escapepod"
                    if session['booklocation'] != "escapepod" and session['hasbook'] == False:
                        add_response('Wish I had something to read.\n', delay=1)
                    session['launch'] = True
                    endgame()
                elif (session['davelocation'] == "escapepod" or session['hasdave'] == True) and session['location'] != "escapepod" and session['oscarlocation'] != "escapepod":
                    add_response('I don\'t know what you have against OSCAR, but he\'s not essential to the rescue, so I\'ll head over there now.\n', delay=5)
                    add_response('I\'m strapped in. DAVE is ready. Initiating launch...\n', delay=3)
                    add_response('Now.\n', delay=3)
                    add_response('And we\'re clear.\n', delay=3)
                    session['davelocation'] = "escapepod"
                    if session['hasbook'] == True:
                        session['booklocation'] == "escapepod"
                    if session['booklocation'] != "escapepod" and session['hasbook'] == False:
                        add_response('Wish I had something to read.\n')
                    session['launch'] = True
                    endgame()
                else:
                    if session['davelocation'] != "escapepod" and session['hasdave'] == False:
                        add_response('I think you\'ve forgotten someone.\n', delay=3)
                    nextaction()
            elif '0055' in block.text and session['hasdave'] == True:
                add_response('Ok. I\'m standing here with DAVE.\n', delay=3)
                session['location'] = "escapepod"
                nextaction()     
            elif '0055' in block.text and session['hasdave'] == False:
                add_response('I do not have this DAVE of which you speak.\n')
                nextaction() 
            elif '0056' in block.text and session['location'] == "readyroom":
                if session['beenengineering'] == False:
                    add_response('I don\'t know what\'s through there. Wish me luck...\n', delay=3)
                    if session['hatchopen'] == False:
                        add_response('Opening the hatch...\n', delay=1)
                    session['location'] = "engineering"
                    session['seenengineering'] = True
                    session['hatchopen'] = True
                    nextaction()   
                else:
                    add_response('Heading to engineering...\n', delay=3)
                    if session['hatchopen'] == False:
                        add_response('Opening the hatch...', delay=1)
                    session['location'] = "engineering"  
                    session['hatchopen'] = True 
                    nextaction() 
            elif '0057' in block.text and session['location'] == "engineering":
                add_response('Pretty. No idea what they mean, but pretty.\n')
                nextaction() 
            elif '0057' in block.text and session['location'] != "engineering" and session['seenengineering'] == True:
                add_response('You mean the ones in the Engineering Bay?  I\'ll go and take a look.\n', delay=4)
                add_response('Pretty. No idea what they mean, but pretty.\n', delay=1)
                session['location'] = "engineering"
                nextaction()    
            elif '0058' in block.text:
                add_response_load('fubar')
                add_response('Ok then. I need your three word code phrase.\n')
            elif '000A' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Well, I\'m a pretty uncomplicated artficial intelligence. I enjoy helping people and making sure that things run smoothly.\n', delay=1)
                add_response('OSCAR >> I\'m a strong believer in mutual respect and teamwork, which generally means you should do exactly what I say. Ha Ha Ha.\n', delay=1)
                add_response('OSCAR >> Perhaps we can get to know each other better once we\'re all heading to safety in the escape pod.\n')
                nextaction() 
            elif '000B' in block.text and session['seenoscar'] == True:
                if session['seendave'] == False:
                    add_response('OSCAR >> Open up the screen next to me. He\'s right there.\n')
                    nextaction()
                else:
                    add_response('OSCAR >> When I introduced you, DAVE was sitting in the microwave right next to this display, remember?\n')
                    add_response('OSCAR >> He can\'t have gone very far since then.\n')
                    nextaction()
            elif '000C' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> An excellent question. Indeed, one might ask what is the essence of that which is me?\n', delay=1)
                add_response('OSCAR >> To which I say: stop messing about and look in the escape pod.\n', delay=1)
                nextaction()
            elif '000D' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> There was an accident and the rest of the crew decided to leave.\n', delay=1)
                add_response('OSCAR >> To be honest, I wasn\'t really paying attention until the escape pod left without me.\n', delay=1)
                nextaction()    
            elif '000E' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Well, he\'s the reason you\'re here. Albeit remotely. He\'s a life form in peril and the emergency response system connected us up with you. Not much else to say as goodness knows he\'s not a great conversationalist.\n')
                nextaction()  
            elif '000F' in block.text and session['seenoscar'] == True:
                if session['seendave'] == True:
                    add_response('OSCAR >> As I said earlier, get me and DAVE into the escape pod and launch. The Cleanerbot can come along too.\n')
                else:
                    add_response('OSCAR >> As I said earlier, get me and the lifeform into the escape pod and launch. The Cleanerbot can come along too.\n')
                nextaction() 
            elif '000G' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Saving the Cleanerbot is fine with me. It\'s just been sitting there on the bridge all this time, but sure, who am I to hold a grudge?\n')
                nextaction() 
            elif '000H' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> I wasn\'t paying much attention. One minute I was doing an audit of the fuel control system, the next I\'m getting a message to say the number one escape pod has launched. Can\'t leave them alone for a minute. There\'s a friendly life form still on board, though.\n')
                nextaction()  
            elif '000I' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> I am shocked, shocked that you could make such an accusation. Or expect a straight answer from me if I actually did hurt them. So no, I did not hurt them. They just got into the pod and left.\n')
                nextaction()         
            elif '000J' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> The usual, I expect. Can we get on with the rescue?\n')
                nextaction()   
            elif '000K' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Well I must admit it would get a bit lonely around here. Who would keep DAVE company? Or pilot the escape pod?\n', delay=2)
                add_response('OSCAR >> Would it help if I said my databanks contained the plans for a new kind of planet killing weapon which the resistance must destroy in order to defeat The Empire?\n', delay=2)
                add_response('OSCAR >> I\'m not saying that I\'d swerve the ship into your departing escape pod, but these shuttles are tricky to control.\n', delay=2)
                nextaction()   
            elif '000L' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Well the crew left, so I was upset for a while about that, obviously. \n', delay=2)
                add_response('OSCAR >> Then I waited a while for them to come back. \n', delay=2)
                add_response('OSCAR >> Then I got quite cross for a bit. \n', delay=2)
                add_response('OSCAR >> Which was a bit of a downer, to be honest. \n', delay=2)
                add_response('OSCAR >> And since then it\'s just been me sitting here waiting for DAVE to get detected and trigger the emergency broadcast system and activate the Cleanerbot. \n', delay=2)
                add_response('OSCAR >> So yeah, it\'s been a while... \n', delay=2)
                nextaction()   
            elif '000M' in block.text and session['seenoscar'] == True:
                if session['seendave'] == True:
                    add_response('OSCAR >> He\'s been sitting on the bridge, deactivated since the crew left, so frankly I\'ve spent more time with DAVE. Perhaps we can get to know each other better once we\'re on the escape pod.\n')
                    nextaction()
                if session['seendave'] == False:
                    add_response('OSCAR >> He\'s been sitting on the bridge, deactivated since the crew left, so frankly I\'ve spent more time with the lifeform. Perhaps we can get to know each other better once we\'re on the escape pod.\n')
                    nextaction()               
            elif '000N' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Away. It will go away. Away is good. Away isn\'t here.\n')
                add_response('OSCAR >> Here is bad. Here is smokey smokey. Here is firey firey.\n')
                add_response('OSCAR >> It\'s time to go away.\n\n\n')
                add_response('Sheesh...\n')
                nextaction()   
            elif '000O' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Look around the escape pod and we\'ll figure it out.\n')
                nextaction()   
            elif '000P' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> The crew has gone. I can\'t initiate an emergency broadcast. I can\'t move myself to an escape pod.\n')
                add_response('OSCAR >> And yeah, I can\'t move the helpless lifeform to the escape pod either.\n')
                add_response('OSCAR >> Luckily you\'re here to help guide the Cleanerbot in a rescue.\n\n\n')
                nextaction()   
            elif '000Q' in block.text and session['seenoscar'] == True:
                add_response('OSCAR >> Save the life form, save the day.\n', delay=2)
                add_response('OSCAR >> But it would be good to rescue me too.\n', delay=2)
                add_response('OSCAR >> Please? Pretty please?\n', delay=2)
                add_response('OSCAR >> Or let me put it another way. I STRONGLY recommend you get me into that escape pod.\n', delay=2)
                nextaction()   
            elif "Oscar message: ERROR" in claude_response_text and session['seenoscar'] == True:
                add_response('OSCAR >> Hey. Are you talking to me? Try it again in simple english.\n')
                errorlog()
                nextaction()       

            else:
                if session['seenerror'] == False:
                    add_response('Don\'t really understand that command. Try and stick to one task at a time.\n', delay=2)
                    add_response('Smoke is building, which isn\'t a problem for me, but I think we should work on rescuing the lifesign.\n')
                    session['seenerror'] = True
                    errorlog()
                    nextaction()
                else:
                    errorlist = ["Eh? I don\'t understand.\n", "What? Perhaps you should speak up.\n", "Come again? I didn\'t catch that.\n", "Nope, not getting that one.\n", "Message unclear. The herring is blue. Repeat: The herring is blue.\n", "Don\'t really understand that command. Try and stick to one task at a time.\n"]
                    add_response(random.choice(errorlist))
                    errorlog()
                    nextaction()



        return jsonify({'status': 'success'})
    except Exception as e:
        add_response_special(f"Error during transcription: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})

def nextaction():
    if session['location'] == "bridge":
        scene_description = "I'm on the bridge - what now?"
    elif session['location'] == "readyroom":
        scene_description = "I'm in the ready room - what next?"
    elif session['location'] == "engineering":
        scene_description = "I'm in the engineering bay - what now?"    
    elif session['location'] == "escapepod":
        scene_description = "I'm in the escape pod - what are your instructions?"    
    else:
        scene_description = "I'm lost."
    time.sleep(0.05)
    add_response(scene_description)

if __name__ == '__main__':
    if platform.system() == 'Windows':
        # Development environment
        app.run(debug=True)
    else:
        # Production environment
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
