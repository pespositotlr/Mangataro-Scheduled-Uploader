# Mangataro Scheduled Uploader

A robust Python automation tool designed to handle batch and direct ZIP uploads to the [Mangataro Hub](https://hub.mangataro.org/dashboard). This script supports scheduling, automatic retry logic, and seamless updates for existing chapters.
This requires you first login and have an account and a group setup on[ Mangataro.org](https://mangataro.org/).

## Features
* **Direct ZIP Uploads**: Bypasses browser-based file count limits by uploading archives directly.
* **Scheduling**: Built-in support for scheduling uploads in **New York (EST/EDT)** timezone.
* **Automatic Retries**: Implements robust retry logic to handle transient network issues or server resets.
* **Intelligent Updates**: Automatically detects if a chapter exists, deletes old images, and uploads the new version.
* **Real-time Feedback**: Includes progress bars and provides the public viewing URL upon successful completion.

## Prerequisites
* **Python 3.11+**

## Installation

```
pip install -r requirements.txt
```
## Configuration

Ensure you have a `config.toml` file in the same directory with the following structure:

Ini, TOML

```
[auth]
email = "your-email@example.com"
password = "your-password"

[settings]
group_id = 123  # Replace with your actual Group ID
```

## Usage

### 1. Basic Immediate Upload

Bash

```
python mangataro_uploader.py "Manga Name" 319.5 "Chapter Title" "path/to/file.zip"
```

### 2. Scheduled Upload

Schedule an upload to run at a specific date and time (New York time):

Bash

```
python mangataro_uploader.py "Manga Name" 319.5 "Chapter Title" "path/to/file.zip" --schedule "2026-05-20 23:30:00"
```

## Key Arguments

|**Argument**|**Description**|
|---|---|
|`manga_name`|The name of the manga (used to look up ID).|
|`chapter_num`|The chapter number (supports decimals like `319.5`).|
|`chapter_title`|The title/name of the chapter.|
|`zip_path`|The local file path to the ZIP archive.|
|`--schedule`|(Optional) Date/Time in `YYYY-MM-DD HH:MM:SS` format.|