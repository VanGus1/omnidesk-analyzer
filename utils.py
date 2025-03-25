import requests
import aiohttp
from aiohttp import BasicAuth
from fastapi import HTTPException, status
import urllib.parse
import re
import html
from datetime import datetime
import json
import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict, Optional, Tuple, Any
from pydantic import BaseModel, Field
import os
from dotenv import load_dotenv
import base64

# Загружаем переменные окружения
load_dotenv()

# Отладочный вывод для проверки переменных окружения
print("Environment variables:")
print(f"OMNIDESK_USERNAME: {'*' * len(os.getenv('OMNIDESK_USERNAME', ''))}")
print(f"OMNIDESK_PASSWORD: {'*' * len(os.getenv('OMNIDESK_PASSWORD', ''))}")

# Модели данных
class Message(BaseModel):
	content: str
	role: str
	sent_at: str
	content_type: str

class Ticket(BaseModel):
	link: str
	case_id: int
	case_number: str
	group_id: int
	user_id: int
	staff_id: int
	rating: Optional[int] = None
	created_at: str
	status: str
	assignee: Optional[str] = None
	group: Optional[str] = None

class AIRequest(BaseModel):
	messages: List[Message]
	ticket: Ticket

# Конфигурация из переменных окружения GitHub Actions
openai_key = os.environ['OPENAI_API_KEY']
SCOPES = os.environ['GOOGLE_SCOPES'].split(',')

# Конфигурация Google Service Account
SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": os.environ['GOOGLE_PROJECT_ID'],
    "private_key_id": os.environ['GOOGLE_PRIVATE_KEY_ID'],
    "private_key": os.environ['GOOGLE_PRIVATE_KEY'],
    "client_email": os.environ['GOOGLE_CLIENT_EMAIL'],
    "client_id": os.environ['GOOGLE_CLIENT_ID'],
    "auth_uri": os.environ['GOOGLE_AUTH_URI'],
    "token_uri": os.environ['GOOGLE_TOKEN_URI'],
    "auth_provider_x509_cert_url": os.environ['GOOGLE_AUTH_PROVIDER_X509_CERT_URL'],
    "client_x509_cert_url": os.environ['GOOGLE_CLIENT_X509_CERT_URL'],
    "universe_domain": "googleapis.com"
}

async def make_get_request(url: str, **kwargs) -> dict:
	"""
	Выполняет асинхронный GET-запрос на указанный URL с использованием переданных параметров.

	Args:
		url: URL для выполнения GET-запроса
		**kwargs: Дополнительные параметры запроса

	Returns:
		dict: Ответ сервера в формате JSON

	Raises:
		HTTPException: Если запрос не удался
	"""
	try:
		# Создаем объект BasicAuth для каждого запроса
		auth = BasicAuth(
			login=os.environ['OMNIDESK_USERNAME'],
			password=os.environ['OMNIDESK_PASSWORD']
		)
		
		async with aiohttp.ClientSession() as session:
			async with session.get(url, auth=auth) as response:
				if response.status != 200:
					error_text = await response.text()
					print(f"Error response: {error_text}")  # Отладочный вывод
					print(f"Request URL: {url}")  # Отладочный вывод
					print(f"Response status: {response.status}")  # Отладочный вывод
					raise HTTPException(
						status_code=response.status,
						detail=f"Ошибка при выполнении запроса: {error_text}"
					)
				return await response.json()
	except Exception as e:
		print(f"Request error: {str(e)}")  # Отладочный вывод
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Ошибка при выполнении запроса: {str(e)}"
		)

async def get_tickets(**kwargs) -> List[Ticket]:
	"""
	Получает список обращений удовлетворяющих условиям
	
	Args:
		**kwargs: Параметры фильтрации обращений
		
	Returns:
		List[Ticket]: Список обращений
		
	Raises:
		HTTPException: Если не удалось получить данные
	"""
	base_url = 'https://profinansy.omnidesk.ru/api/cases.json'
	params = kwargs
	limit = params.get('limit', 100)
	all_results = []
	page = 1
	total_fetched = 0

	while True:
		params['page'] = page
		url = f"{base_url}?{urllib.parse.urlencode(params)}"
		print(f"Fetching tickets from URL: {url}")  # Отладочный вывод

		try:
			cases = await make_get_request(url)
			print(f"Received response: {cases}")  # Отладочный вывод
			
			if not isinstance(cases, dict):
				raise ValueError(f"Unexpected response format: {type(cases)}")
				
			results = []
			for c in cases:
				if c == 'total_count':
					continue
					
				if not isinstance(cases[c], dict) or 'case' not in cases[c]:
					print(f"Skipping invalid case format: {cases[c]}")  # Отладочный вывод
					continue
					
				case = cases[c]["case"]
				try:
					ticket = Ticket(
						link=f'https://profinansy.omnidesk.ru/staff/cases/record/{case["case_number"]}',
						case_id=case["case_id"],
						case_number=case["case_number"],
						group_id=case["group_id"],
						user_id=case["user_id"],
						staff_id=case["staff_id"],
						rating=case.get("rating"),  # Используем .get() для опциональных полей
						created_at=case["created_at"],
						status=case['status'],
					)
					results.append(ticket)
				except Exception as e:
					print(f"Error creating ticket from case {case.get('case_id')}: {str(e)}")  # Отладочный вывод
					continue

			all_results.extend(results)
			total_fetched += len(results)
			print(f"Processed {len(results)} tickets on page {page}")  # Отладочный вывод

			if len(results) < 100 or (limit is not None and total_fetched >= limit):
				break
			else:
				page += 1
				
		except Exception as e:
			print(f"Error in get_tickets: {str(e)}")  # Отладочный вывод
			raise HTTPException(
				status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
				detail=f"Ошибка при получении обращений: {str(e)}"
			)

	return all_results[:limit] if limit else all_results

async def get_messages(case_id: int) -> List[Message]:
	"""
	Получает список сообщений из обращения
	
	Args:
		case_id: ID обращения
		
	Returns:
		List[Message]: Список сообщений
		
	Raises:
		HTTPException: Если не удалось получить сообщения
	"""
	url = f'https://profinansy.omnidesk.ru/api/cases/{case_id}/messages.json'

	try:
		response = await make_get_request(url)
		data = response.json()
		messages = []

		for key, value in data.items():
			if key == "total_count":
				continue

			message = value.get('message', {})
			content = message.get('content', '')
			content_type = 'tg' if content else 'email'
			content = content if content else message.get('content_html', '')

			message_type = message.get('message_type', '')
			role = "user" if message_type == "reply_user" else "staff" if message_type == "reply_staff" else "system"

			messages.append(Message(
				content=content,
				role=role,
				sent_at=message.get('sent_at', ''),
				content_type=content_type
			))

		return messages
	except Exception as e:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Ошибка при получении сообщений: {str(e)}"
		)

def clean_message(text, content_type):
	'''
	Очищает сообщения от метаданных
	'''
	if content_type == 'tg':
		if text.startswith('[lastMessageId:'):
			text = re.sub(r'^\[lastMessageId:.*?\] :', '', text, flags=re.DOTALL).strip()
			if text.startswith('Пользователь отредактировал сообщение:'):
				text = re.sub(r'^(Пользователь отредактировал сообщение:\n\n)', '', text, flags=re.DOTALL).strip()
				pattern = r"\s+"
				text = re.sub(pattern, " ", text).strip()
				return text
			pattern = r"\s+"
			text = re.sub(pattern, " ", text).strip()
			return text
		elif bool(re.match(r'^#\d{1,10}', text)):
			pattern = r'Уточните, пожалуйста, в чем именно заключается ваш вопрос\?\s*(.*?)\s*Сейчас мы отвечаем чуть дольше, чем обычно\. Не переживайте, мы рядом и обязательно напишем вам :heart:'
			text = re.search(pattern, text, flags=re.DOTALL)
			if text:
				text = text.group(1).strip()
				pattern = r"\[\d{2}:\d{2} \| [^\]]+\] : (.+)"
				text = re.search(pattern, text)
				
				if text: 
					return text.group(1).strip()
				else:
					return None
			else:
				return None
		else:
			pattern = r"(.*?)(?:\n[^\n]+)$"
			text = re.sub(pattern, r'\1', text, flags=re.DOTALL).strip()
			pattern = r"\s+"
			text = re.sub(pattern, " ", text).strip()
			return text
	elif content_type == 'email':
		text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<.*?>', ' ', text))).strip()
		return text
	
def role_count(messages):
	'''
	
	'''
	staff_count = 0
	user_count = 0

	for message in messages:
		if message['role'] == 'staff':
			staff_count += 1
		elif message['role'] == 'user':
			user_count += 1

	return (staff_count, user_count)

async def get_staff_dict() -> Dict[int, str]:
	"""
	Формирует словарь сотрудников
	
	Returns:
		Dict[int, str]: Словарь {staff_id: staff_name}
		
	Raises:
		HTTPException: Если не удалось получить данные сотрудников
	"""
	try:
		response = await make_get_request('https://profinansy.omnidesk.ru/api/staff.json')
		staff_data = response.json()
		return {
			item["staff"]["staff_id"]: item["staff"]["staff_full_name"]
			for item in staff_data.values()
			if isinstance(item, dict) and "staff" in item
		}
	except Exception as e:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Ошибка при получении данных сотрудников: {str(e)}"
		)

async def get_group_dict() -> Dict[int, str]:
	"""
	Формирует словарь групп обращений
	
	Returns:
		Dict[int, str]: Словарь {group_id: group_name}
		
	Raises:
		HTTPException: Если не удалось получить данные групп
	"""
	try:
		response = await make_get_request('https://profinansy.omnidesk.ru/api/groups.json')
		group_data = response.json()
		return {
			item["group"]["group_id"]: item["group"]["group_title"]
			for item in group_data.values()
			if isinstance(item, dict) and "group" in item
		}
	except Exception as e:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Ошибка при получении данных групп: {str(e)}"
		)

async def set_assignee(tickets: List[Ticket]) -> List[Ticket]:
	"""
	Определяет ответственных у обращений
	
	Args:
		tickets: Список обращений
		
	Returns:
		List[Ticket]: Список обращений с назначенными ответственными
	"""
	staff_dict = await get_staff_dict()
	for ticket in tickets:
		ticket.assignee = staff_dict.get(ticket.staff_id, "Ответственный не назначен")
	return tickets

async def set_group(tickets: List[Ticket]) -> List[Ticket]:
	"""
	Определяет группу обращения
	
	Args:
		tickets: Список обращений
		
	Returns:
		List[Ticket]: Список обращений с определенными группами
	"""
	group_dict = await get_group_dict()
	for ticket in tickets:
		ticket.group = group_dict.get(ticket.group_id, "Группа не указана")
	return tickets

def get_earliest_message(messages):
	try:
		staff_messages = [message for message in messages if message["role"] == "staff"]

		earliest_message = min(staff_messages, key=lambda msg: parse_sent_at(msg["sent_at"]))
		time = earliest_message['sent_at']
	except ValueError:
		time = 0
	
	return time

def parse_sent_at(sent_at_str):
	return datetime.strptime(sent_at_str, "%a, %d %b %Y %H:%M:%S %z")

def get_first_response(a, b):
	try:
		date_format = '%a, %d %b %Y %H:%M:%S %z'
		date_a = datetime.strptime(a, date_format)
		date_b = datetime.strptime(b, date_format)

		time_difference = date_b - date_a

		difference_in_minutes = time_difference.total_seconds() / 60
	except TypeError:
		difference_in_minutes = 0

	return difference_in_minutes

def make_request_ai(data):

	if not data:
		return None

	prompt = [
		{
			"role": "system",
			"content": (
				'Проанализировать диалоги пользователей с клиентской поддержкой для оценки их качества по различным критериям.'
				'Диалоги представлены в формате JSON, содержащем список сообщений (**messages**), где:'
				'- **content** – текст сообщения'
				'- **role** – роль отправителя (оператор/пользователь)'
				'- **sent_at** – время отправки сообщения'
				'- Выделите ключевые моменты диалога: приветствие, выявление проблемы, решение, завершение.'
				'- **Определение уровня сложности обращения**'
				'- **Сложный уровень:**'
					'- Вопросы по IT'
					'- Вопросы по оплате'
					'- Вопросы про книгу *"33 заметки о финансах"*'
					'- Вопросы по возвратам'
					'- Вопросы, где оператор уточняет информацию и обещает вернуться с ответом'
				'- **Средний уровень:**'
					'- Вопросы по подключению подарков'
					'- Запросы от сотрудников'
					'- Запросы по доступам'
				'- **Простой уровень:** все остальные'
				'- **Оценка времени решения вопроса**'
				'- Время исчисляется с момента поступления вопроса до отправки сообщения, запрашивающего у клиента подтверждение о решении вопроса.'
				'- Примеры завершающих формулировок:'
					'- *Ваш вопрос решен?*'
					'- *Можем ли мы еще чем-нибудь вам помочь?*'
					'- *Остались ли у вас еще вопросы?*'
				'- **Оценка решения вопроса**'
				'- Решен ли вопрос клиента: **да/нет**.'
				'- **Комментарий к решению вопроса**'
				'- Укажите, в чем состоял вопрос и какое решение предложил оператор.'
				'- Комментарий должен быть списком фактов, без субъективного анализа.'
				'- **Оценка и баллы за решение вопроса**'
				'- Если подтверждение от клиента есть – **вопрос решен**.'
				'- Если подтверждения нет – анализируется контекст.'
				'- Оценка баллов:'
					'- **1 вопрос – 5 баллов**, если решения нет – **-5 баллов**.'
					'- **Несколько вопросов:** за каждую пару *вопрос-решение* начисляется **2,5 балла**.'
				'- **Оценка манеры общения**'
				'- Проверка соответствия корпоративному **Tone of Voice**:'
					'- Забавный, но не глупый'
					'- Самоуверенный, но не дерзкий'
					'- Умный, но не всезнайка'
					'- Официальный, но не занудный'
					'- Экспертный, но не поучительный'
				'- Проверьте, были ли ошибки:'
					'- Нет обращения по имени'
					'- Использование запрещенных выражений'
					'- Отсутствие вежливости (не поблагодарил за ожидание, не извинился)'
				'- Не вычитайте баллы за наличие рекламных вставок (приглашение на мероприятие, предложение продукта).'
				'- **Комментарий к манере общения**'
				'- Укажите, какие выражения следовало использовать и замените некорректные формулировки.'
				'- **Рекомендации по улучшению**'
				'- Опишите, что нужно улучшить в данном диалоге и что отсутствовало.'
				'**Начальная оценка:** 10 баллов'
				'**Отнимать баллы, если были нарушены:**'
				'- **Отсутствует решение вопроса** – 5 баллов'
				'- **Манера общения не соответствует Tone of Voice** – 2 балла'
				'- **Время первого ответа (больше 30 минут)** – 2 балла'
				'- **Отсутствует приглашение на мероприятие/покупку продукта** – 1 балл'
				'---'
				'Результат анализа должен быть представлен в формате JSON:'
				'```json'
				'{'
				'"difficulty_level": "[уровень сложности обращения (Простой/Средний/Сложный)]",'
				'"time_spent": "[время, затраченное на решение обращения (int)]",'
				'"is_solved": "[решен ли вопрос пользователя (str)]",'
				'"solution_comment": "[комментарий к решению вопроса (list)]",'
				'"solution_score": "[баллы за решение вопроса (int)(0-2)]",'
				'"communication_style": "[манера общения сотрудника (str)(Соответствует/не соответствует Tone of Voice)]",'
				'"communication_comment": "[комментарий к манере общения (str)]",'
				'"communication_score": "[баллы за манеру общения (int)]",'
				'"total_score": "[итоговая оценка качества диалога (int)(0-10)]",'
				'"improvement_recommendations": "[рекомендации по улучшению (str)]"'
				'}'
				'```'
				'- Игнорируйте рекламные вставки в ответах оператора.'
				'- Анализируйте не только текст, но и контекст общения (например, срочность проблемы и предыдущее взаимодействие).'

			)
		},
		{
			"role": "user",
			"content": json.dumps(data)
		}
	]

	url = 'https://api.openai.com/v1/chat/completions'
	token = openai_key

	headers = {
		'Authorization': f'Bearer {token}'
	}

	data = {
		'model': 'gpt-4o-2024-08-06',
		'messages': prompt,
	}

	retries = 0
	max_retries = 5

	while retries < max_retries:
		try:
			response = requests.post(url, headers=headers, json=data)

			if response.status_code == 200:
				response_data = response.json()

				extracted_content = response_data["choices"][0]["message"]["content"]

				json_match = re.search(r'```json\n(.*?)\n```', extracted_content, re.DOTALL)

				if json_match:
					extracted_json = json_match.group(1)
				else:
					extracted_json = extracted_content

				try:
					parsed_data = json.loads(extracted_json)
					return parsed_data
				except json.JSONDecodeError as e:
					raise ValueError(f"Ошибка при парсинге JSON: {e}\n{extracted_json}")
			else:
				retries += 1
				continue

		except requests.RequestException as e:
			retries += 1
			continue

	return None


def init_google_sheets():
	creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
	client = gspread.authorize(creds)
	return client

def flatten_value(value):
	if isinstance(value, list):
		return "\n".join([str(item) for item in value])
	if isinstance(value, dict):
		return str(value)
	return value

def create_tickets_table(client, tickets, spreadsheet_name="Обращения"):
	"""
	Создает таблицу с обращениями и записывает в нее данные.
	:param client: Клиент Google Sheets
	:param tickets: Список обращений
	:param spreadsheet_name: Название таблицы (по умолчанию "Обращения")
	:return: Объект таблицы (spreadsheet), объект листа (sheet) и заголовки (headers)
	"""

	spreadsheet = client.create(spreadsheet_name)
	spreadsheet.share('e.rodnykh@gmail.com', perm_type='user', role='writer')
	sheet = spreadsheet.sheet1

	headers = [
		'link', 'case_id', 'user_id', 'rating',
		'created_at', 'status', 'staff_count', 'user_count',
		'earliest_message', 'assignee', 'group', 'first_response_score'
	]
	data_list = [headers]

	for ticket in tickets:
		row = [flatten_value(ticket[key]) for key in headers]
		data_list.append(row)

	sheet.update('A1', data_list)

	print(f"Таблица '{spreadsheet_name}' создана и доступна по ссылке: {spreadsheet.url}")
	return spreadsheet, sheet, headers

def update_table_with_ai_results(sheet, ticket, headers, row_index):
	"""
	Добавляет данные из ai_result в таблицу для конкретного ticket.
	:param sheet: Объект листа Google Sheets
	:param ticket: Обращение с добавленным ai_result
	:param headers: Заголовки таблицы (список)
	:param row_index: Индекс строки, в которую нужно добавить данные
	"""

	try:
		ai_headers = [
			'difficulty_level', 'time_spent', 'is_solved', 'solution_comment',
			'solution_score', 'communication_style', 'communication_comment',
			'communication_score', 'total_score', 'improvement_recommendations'
		]

		if row_index == 2:
			sheet.update(
				f"{gspread.utils.rowcol_to_a1(1, len(headers) + 1)}:{gspread.utils.rowcol_to_a1(1, len(headers) + len(ai_headers))}",
				[ai_headers]
			)

		ai_result = ticket.get('ai_result', {})
		ai_row = [flatten_value(ai_result.get(key, '')) for key in ai_headers]

		sheet.update(
			f"{gspread.utils.rowcol_to_a1(row_index, len(headers) + 1)}:{gspread.utils.rowcol_to_a1(row_index, len(headers) + len(ai_headers))}",
			[ai_row]
		)

		print(f"Данные из ai_result для ticket {ticket['case_id']} добавлены в таблицу.")
	except AttributeError:
		pass