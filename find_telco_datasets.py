# Script to fetch and list telecom-related datasets from Hugging Face using the official API.
# This approach uses the huggingface_hub library to avoid web scraping and potential DDoS issues.
# It performs searches for relevant terms and collects unique dataset IDs.
# No data is modified on the source; this is read-only.
# Install the required library if not already installed: pip install huggingface_hub

from huggingface_hub import HfApi
import time

# Initialize the Hugging Face API client
api = HfApi()

# Define search terms related to telecom. You can expand this list as needed.
search_terms = [
    "telecom",
    "telecommunication",
    "telephony",
    "mobile network",
    "wireless communication",
    "5G",
    "LTE",
    "GSM",
    "cellular network",
    "signal processing telecom",
    "tele*"
]

# Set to store unique dataset IDs
telecom_datasets = set()

# Iterate over each search term
for term in search_terms:
    print(f"Searching for datasets with term: {term}")
    try:
        # List datasets matching the search term. This uses pagination internally.
        for dataset in api.list_datasets(search=term):
            telecom_datasets.add(dataset.id)
    except Exception as e:
        print(f"Error during search for '{term}': {e}")
    # Add a small delay to be polite to the API (avoids rapid requests)
    time.sleep(1)

# Sort the dataset IDs alphabetically
sorted_datasets = sorted(telecom_datasets)

# Write the list to a local text file
output_file = "telecom_datasets.txt"
with open(output_file, "w") as f:
    for ds_id in sorted_datasets:
        f.write(f"{ds_id}\n")

print(f"Found {len(sorted_datasets)} unique telecom-related datasets.")
print(f"List written to '{output_file}'.")