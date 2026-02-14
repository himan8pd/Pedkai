from datasets import load_dataset

dataset = load_dataset("AliMaatouk/telecom_ts")

# Check dataset structure
print(dataset)

# Inspect column names
print(dataset['train'].column_names)

# Peek at first few rows
for i in range(1):
    print(dataset['train'][i])
    