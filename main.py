import os
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv('/etc/systemd/system/omnidesk-analyzer.env')

# Отладочный вывод
print("Environment variables:")
for key in ['OMNIDESK_USERNAME', 'OMNIDESK_PASSWORD', 'OPENAI_API_KEY', 'GOOGLE_SERVICE_ACCOUNT_FILE']:
	print(f"{key}: {'*' * len(os.getenv(key, '')) if os.getenv(key) else 'Not set'}")

from fastapi import FastAPI, HTTPException
from typing import List, Optional
from utils import get_tickets, get_messages, clean_message, role_count, set_assignee, set_group, get_earliest_message, make_request_ai, get_first_response, create_tickets_table, init_google_sheets, update_table_with_ai_results
from pydantic import BaseModel

app = FastAPI(
	title="OmniDesk Analyzer API",
	description="API для анализа обращений в системе OmniDesk",
	version="1.0.0"
)

class TicketResponse(BaseModel):
	case_id: int
	case_number: str
	status: str
	created_at: str
	staff_count: Optional[int] = None
	user_count: Optional[int] = None
	earliest_message: Optional[str] = None
	first_response_score: Optional[float] = None
	assignee: Optional[str] = None
	group: Optional[str] = None

class AnalyzeRequest(BaseModel):
	ticket_ids: List[int]
	assignee: Optional[str] = None
	group: Optional[str] = None

@app.get("/")
async def root():
	return {"message": "OmniDesk Analyzer API is running"}

@app.get("/tickets", response_model=List[TicketResponse])
async def get_tickets_list(limit: int = 10, status: str = 'closed'):
	"""
	Получение списка тикетов
	"""
	try:
		logger.info(f"Fetching tickets with limit={limit} and status={status}")
		tickets = await get_tickets(limit=limit, status=status)
		logger.info(f"Found {len(tickets)} tickets")
		
		# Преобразуем тикеты в формат ответа
		response_tickets = []
		for ticket in tickets:
			try:
				response_ticket = TicketResponse(
					case_id=ticket['case_id'],
					case_number=ticket['case_number'],
					status=ticket['status'],
					created_at=ticket['created_at'],
					staff_count=ticket.get('staff_count'),
					user_count=ticket.get('user_count'),
					earliest_message=ticket.get('earliest_message'),
					first_response_score=ticket.get('first_response_score'),
					assignee=ticket.get('assignee'),
					group=ticket.get('group')
				)
				response_tickets.append(response_ticket)
			except Exception as e:
				logger.error(f"Error processing ticket {ticket.get('case_id')}: {str(e)}")
				continue
		
		logger.info(f"Successfully processed {len(response_tickets)} tickets")
		return response_tickets
		
	except Exception as e:
		logger.error(f"Error fetching tickets: {str(e)}", exc_info=True)
		raise HTTPException(
			status_code=500,
			detail=f"Error fetching tickets: {str(e)}"
		)

@app.get("/tickets/{case_id}/messages")
async def get_ticket_messages(case_id: int):
	"""
	Получение сообщений конкретного обращения
	"""
	try:
		messages = get_messages(case_id)
		for message in messages:
			cleaned_content = clean_message(message['content'], message['content_type'])
			message['content'] = cleaned_content
		return messages
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze")
async def analyze_tickets(request: AnalyzeRequest):
	try:
		logger.info(f"Starting analysis for tickets: {request.ticket_ids}")
		logger.info(f"Additional parameters - assignee: {request.assignee}, group: {request.group}")
		
		# Получаем тикеты
		logger.debug("Fetching tickets...")
		tickets = get_tickets(request.ticket_ids)
		logger.info(f"Found {len(tickets)} tickets")
		
		# Получаем сообщения для каждого тикета
		logger.debug("Fetching messages for tickets...")
		messages = {}
		for ticket in tickets:
			try:
				logger.debug(f"Fetching messages for ticket {ticket['id']}")
				messages[ticket['id']] = get_messages(ticket['id'])
				logger.info(f"Found {len(messages[ticket['id']])} messages for ticket {ticket['id']}")
			except Exception as e:
				logger.error(f"Error fetching messages for ticket {ticket['id']}: {str(e)}")
				raise HTTPException(status_code=500, detail=f"Error fetching messages for ticket {ticket['id']}: {str(e)}")
		
		# Очищаем сообщения
		logger.debug("Cleaning messages...")
		cleaned_messages = {}
		for ticket_id, msgs in messages.items():
			cleaned_messages[ticket_id] = [clean_message(msg) for msg in msgs]
		
		# Подсчитываем роли
		logger.debug("Counting roles...")
		roles = {}
		for ticket_id, msgs in cleaned_messages.items():
			roles[ticket_id] = role_count(msgs)
		
		# Получаем первое сообщение
		logger.debug("Getting earliest messages...")
		first_messages = {}
		for ticket_id, msgs in cleaned_messages.items():
			first_messages[ticket_id] = get_earliest_message(msgs)
		
		# Получаем ответы от AI
		logger.debug("Getting AI responses...")
		ai_responses = {}
		for ticket_id, msg in first_messages.items():
			try:
				logger.debug(f"Getting AI response for ticket {ticket_id}")
				ai_responses[ticket_id] = make_request_ai(msg)
				logger.info(f"Got AI response for ticket {ticket_id}")
			except Exception as e:
				logger.error(f"Error getting AI response for ticket {ticket_id}: {str(e)}")
				raise HTTPException(status_code=500, detail=f"Error getting AI response for ticket {ticket_id}: {str(e)}")
		
		# Получаем время первого ответа
		logger.debug("Getting first response times...")
		first_response_times = {}
		for ticket_id, msgs in cleaned_messages.items():
			first_response_times[ticket_id] = get_first_response(msgs)
		
		# Создаем таблицу
		logger.debug("Creating tickets table...")
		try:
			table = create_tickets_table(tickets, cleaned_messages, roles, ai_responses, first_response_times)
			logger.info("Table created successfully")
		except Exception as e:
			logger.error(f"Error creating table: {str(e)}")
			raise HTTPException(status_code=500, detail=f"Error creating table: {str(e)}")
		
		# Инициализируем Google Sheets
		logger.debug("Initializing Google Sheets...")
		try:
			sheet = init_google_sheets()
			logger.info("Google Sheets initialized successfully")
		except Exception as e:
			logger.error(f"Error initializing Google Sheets: {str(e)}")
			raise HTTPException(status_code=500, detail=f"Error initializing Google Sheets: {str(e)}")
		
		# Обновляем таблицу
		logger.debug("Updating table with AI results...")
		try:
			update_table_with_ai_results(sheet, table)
			logger.info("Table updated successfully")
		except Exception as e:
			logger.error(f"Error updating table: {str(e)}")
			raise HTTPException(status_code=500, detail=f"Error updating table: {str(e)}")
		
		# Устанавливаем assignee и group если указаны
		if request.assignee:
			logger.debug(f"Setting assignee to {request.assignee}...")
			for ticket_id in request.ticket_ids:
				set_assignee(ticket_id, request.assignee)
		
		if request.group:
			logger.debug(f"Setting group to {request.group}...")
			for ticket_id in request.ticket_ids:
				set_group(ticket_id, request.group)
		
		logger.info("Analysis completed successfully")
		return {"status": "success", "message": "Analysis completed successfully"}
		
	except Exception as e:
		logger.error(f"Error during analysis: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
	import uvicorn
	uvicorn.run(app, host="0.0.0.0", port=8000)