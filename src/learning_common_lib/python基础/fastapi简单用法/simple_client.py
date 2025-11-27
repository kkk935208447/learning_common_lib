import requests

params = {
    'name': "John",
    # 'name': "John2",
    'age': 30,
}

url = 'http://127.0.0.1:8040/test'
# url = "http://47.93.0.103:3003/test"
res = requests.post(url, json=params)

print(res.text)
print(res.json())