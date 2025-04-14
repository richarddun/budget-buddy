from ollama import chat

response = chat(
    model='llama3.2:latest',  # Or 'llama3.2' if you've tagged it that way locally
    messages=[
        {'role': 'user', 'content': 'Why is the sky blue?'}
    ]
)

print(response['message']['content'])
