from fastapi import FastAPI

# Создаем само приложение
app = FastAPI(title="Учет продуктов КБЖУ")

# Наш первый тестовый эндпоинт (маршрут)
@app.get("/")
def read_root():
    return {"message": "Привет! Бэкенд приложения учета продуктов запущен!"}