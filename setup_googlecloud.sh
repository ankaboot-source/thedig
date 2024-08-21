#!/bin/bash

# Help set-up the whole API keys

# You can modify this
APP_NAME="thedig"
SERVICE_ACCOUNT="${APP_NAME}-ai" # Using a single service account for Vision and Vertex
GOOGLE_CREDENTIALS="./google-credentials-thedig.json" # The path where to generate google keys

# Create project and switch to it
gcloud projects create $APP_NAME
gcloud config set project $APP_NAME

# --- Google Cloud Platform ---

# Enable Vision API
gcloud services enable vision.googleapis.com

# Enable Custom Search
gcloud services enable customsearch.googleapis.com

# Enable Vertex AI API
gcloud services enable aiplatform.googleapis.com

# Enable Datastore API
gcloud services enable datastore.googleapis.com

# Create service account for Vision and Vertex AI
gcloud iam service-accounts create $SERVICE_ACCOUNT \
  --display-name "${APP_NAME} AI"

# Create the key as JSON file 
gcloud iam service-accounts keys create "${GOOGLE_CREDENTIALS}" \
  --iam-account "${SERVICE_ACCOUNT}@${APP_NAME}.iam.gserviceaccount.com"

# --- Vertex AI Search Setup ---

# Datastore Index
DATASTORE_ID="linkedin-index-$(date +%s)" # Example: Generate a unique ID
gcloud datastore indexes create index.yaml --index-id="$DATASTORE_ID"

# Vertex AI Search Index
# Cron scheduele: Crawl daily at midnight UTC
cat << EOF > linkedinprofileindex.json
{
  "displayName": "LinkedIn Profile Index",
  "metadataSchemaUri": "gs://google-cloud-aiplatform/schema/search/metadata_1.0.0.yaml",
  "dataSource": {
    "dataStoreId": "$DATASTORE_ID",
    "crawlConfig": {
      "crawlSchedule": {
        "cron": "0 0 * * *"
      },
      "requiredSchemaMarker": "CUSTOM_EXTRACTED_REQUIRED_FIELDS",
      "urlWhitelistPatterns": [
        "*.linkedin.com/in/*"
      ]
    }
  }
}
EOF

curl -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d @linkedinprofileindex.json \
  "https://us-central1-aiplatform.googleapis.com/v1/projects/${APP_NAME}/locations/us-central1/indexes" | jq -r '.name' | cut -d'/' -f6


echo "Remember to manually create and configure Azure Bing Search and Brave Search credentials."
echo "Configure only your Google Custom Search Engine, then copy/paste the cx value to your .env file"
echo "-------------------------"
echo "Copy/paste following lines to your .env"
echo "\$GOOGLE_CREDENTIALS=\"${GOOGLE_CREDENTIALS}\""
echo "\$GOOGLE_VERTEXAI_DATASTORE=\"${DATASTORE_ID}\""
echo "\$GOOGLE_VERTEXAI_PROJECTID=\"$(gcloud config get-value project)\""
