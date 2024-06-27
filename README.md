# cleanerbot_rescue

Can cheap, fast, Natural Language Processing be the brains inside a game? Could I find out without building just another chatbot?

Well, yeah -here's the code. And I even wrote:

 - a blogpost on buiding [a local-hosted version you can run on your own machine](https://andresvarela.com/2024/06/cleanerbot-rescue-part-1/) over in [this other repo](https://github.com/ThatAndresV/cleanerbot-rescue-local)
 - a blogpost about [updating the local version to run on the web](https://andresvarela.com/2024/06/cleanerbot-rescue-part-2/) - you should probably read this as it's about this repo
 - a deployed version of the repo you're looking at now which you can [play for yourself online](https://dulcet-buttress-422311-g5.et.r.appspot.com/)
 - and even a [completely no-code implementation](https://andresvarela.com/2024/06/cleanerbot-rescue-part-3/)

You (the player) are communicating remotely with a distant Cleanerbot, directing it on a search and rescue mission on a burning spaceship to excuse any latency between input and response.  You speak rather than type your inputs. This is a 21st century text adventure after all.

The `index.html` file is the web interface which triggers the start of a new session on load, then records audio from the player and passes it to the Flask file, `main.py`.

This Flask application uses Google Cloud Speech-to-Text for voice commands and the Claude API for processing. Claude's response is compared to a large IF statement ('game logic') which then determines what information is written to a response_log.

That response_log is then parsed and presented to the player on a webpage. Most commonly, the responses use the function add_response() or add_response_special() which are just ways of informing what CSS the webage should use to present the response. 


## Features

- **Voice Commands**: Users can send commands through voice recordings.
- **Session Management**: Each user session is uniquely identified and managed.
- **Responsive Design**: The application is optimized for both desktop and mobile devices.
- **Game State Saving**: Players can save and load their game state using unique phrases.
- **Error Logging**: Tracks and logs errors encountered during gameplay.
- **Voice Command Handling**: Processes voice commands to interact with the game.

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Code Overview](#code-overview)
- [Contributing](#contributing)
- [License](#license)

## Installation

1. **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/cleanerbot-rescue.git
    ```

2. **Navigate to the project directory**:
    ```bash
    cd cleanerbot-rescue
    ```

3. **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate   # On Windows, use `venv\Scripts\activate`
    ```

4. **Install the dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

5. **Set up Google Cloud Storage**:
    Ensure you have a GCS bucket set up and have the necessary credentials stored in an environment variable `GOOGLE_APPLICATION_CREDENTIALS`.
	
	
6. **Populate your Google Cloud Storage bucket**
	Unzip the files in GCS.zip and upload them to the bucket:
	- `baseprompt.txt` - separated from the flask file for easier admin
	- `s1.txt`, `s2.txt`, `s3.txt` - word lists used for saving a player's game state
	- `gamesaves.txt`- csv containing saved games and their code phrases
	- `actioncounts.txt` and `errorcounts.txt` - used in the player's report card when they complete the game.
	
7. **Set up Google App Engine**:
	You'll need to create an area in which you can host the game. That's where all the other files go.


## Congiguration

**Environment Variables**:
	- `your_anthropic_api_key`: Your Anthropic API key
    - `GOOGLE_APPLICATION_CREDENTIALS`: Path to your Google Cloud credentials JSON file.
    - `GCS_BUCKET_NAME`: The name of your GCS bucket.

## Code Overview

I've split this between `index.html` and `main.py`.

### index.html Structure

The main structure of the application is defined in the `index.html` file. It includes:

- **Header**: Contains metadata and links to external resources.
- **Body**:
  - A header (`<h1>`) for the game title.
  - A content div (`.content`) to display responses.
  - A footer (`.footer`) with buttons for user interaction.

### index.html CSS Styling

The styles are embedded within the `<style>` tag in the `index.html` file. Key styles include:

- **Background and Text**: Customized to create a gaming atmosphere.
- **Buttons**: Styled for various states (enabled, disabled, mouseover).

### index.html JavaScript Functionality

The JavaScript code handles:

- **Voice Recording**: Uses the `MediaRecorder` API to capture audio.
- **Session Management**: Generates and manages unique session IDs for users.
- **Dynamic Content**: Updates the content and footer based on user interactions and responses.

### index.html Dependencies

- **Font Awesome**: For icons used in the footer.
- **Audio Recorder Polyfill**: To ensure compatibility across browsers for audio recording.


### Flask Main Functions

- **record_endpoint()**: Processes the audio input to text, sends that text to Claude, and applies Claude's response to a great big IF statement of game logic.
- **add_response()**: Adds a new entry to the response_log in the player's session file, which `index.html` parses and displays on the webpage.

### Flask Error Handling

Errors encountered during gameplay are logged, and appropriate messages are returned to the player.

### Flask Session Management

Each player's session is controlled through a unique session file stored in Google Cloud Storage. Note that while we have mechanisms for closing a session (for example inactivity of >30 mins) there's no mechanism for preiodically clearing 'dead' session files. You can handle this with a cron job.



## Contributing

Contributions are welcome! Please follow these steps to contribute:

1. **Fork the repository**.
2. **Create a new branch**:
    ```bash
    git checkout -b feature-branch
    ```
3. **Make your changes**.
4. **Commit your changes**:
    ```bash
    git commit -m "Description of changes"
    ```
5. **Push to your branch**:
    ```bash
    git push origin feature-branch
    ```
6. **Create a pull request**.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
