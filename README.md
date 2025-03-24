# OmniDesk Analyzer

Сервис для анализа обращений в системе OmniDesk с использованием AI.

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/your-username/omnidesk-analyzer.git
cd omnidesk-analyzer
```

2. Создайте виртуальное окружение и активируйте его:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
venv\Scripts\activate     # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл .env и добавьте необходимые переменные окружения:
```
OMNIDESK_USERNAME=your_username
OMNIDESK_PASSWORD=your_password
OPENAI_API_KEY=your_openai_key
```

## Запуск

```bash
uvicorn main:app --reload
```

## API Endpoints

- `GET /tickets` - Получение списка обращений
- `GET /tickets/{case_id}/messages` - Получение сообщений конкретного обращения
- `POST /analyze` - Анализ обращения с помощью AI

## Развертывание

Проект автоматически развертывается на сервере при пуше в ветку main через GitHub Actions. 