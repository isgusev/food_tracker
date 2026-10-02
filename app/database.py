from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# URL для подключения к базе данных. 
# Пока мы не развернули базу на Amvera, мы можем использовать временную локальную базу 
# или подготовить строку для подключения. Для теста на будущее формат такой:
# SQLALCHEMY_DATABASE_URL = "postgresql://user:password@localhost:5432/food_db"

# Для того чтобы ты мог тестировать код прямо сейчас без поднятия тяжелой PostgreSQL на Маке,
# мы временно (!) переключимся на легкую встроенную SQLite. Она создаст файл прямо в папке.
# Как только будем деплоить на Amvera — заменим эту строчку на PostgreSQL одной левой.
SQLALCHEMY_DATABASE_URL = "sqlite:///./food_tracker.db"

# Создаем движок базы данных
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Создаем фабрику сессий (чтобы открывать/закрывать запросы к БД)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс, от которого будут наследоваться все наши таблицы
Base = declarative_base()

# Функция-помощник, которая будет давать доступ к БД при каждом запросе сайта
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()