import os
from dotenv import load_dotenv

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

@app.get("/")
async def root():
	return {"message": "OmniDesk Analyzer API is running"}

@app.get("/tickets", response_model=List[TicketResponse])
async def get_tickets_list(limit: int = 10, status: str = 'closed'):
	"""
	Получение списка обращений с возможностью фильтрации
	"""
	try:
		tickets = get_tickets(limit=limit, status=status)
		set_assignee(tickets)
		set_group(tickets)
		return tickets
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))

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
async def analyze_tickets(limit: int = 10, status: str = 'closed'):
	"""
	Полный анализ обращений с записью в Google Sheets
	"""
	try:
		client = init_google_sheets()
		tickets = get_tickets(limit=limit, status=status)
		
		for ticket in tickets:
			try:
				messages = get_messages(ticket['case_id'])
				for message in messages:
					cleaned_content = clean_message(message['content'], message['content_type'])
					message['content'] = cleaned_content
					
				ticket['messages'] = messages
				(staff_count, user_count) = role_count(messages)
				ticket['staff_count'] = staff_count
				ticket['user_count'] = user_count
				ticket['earliest_message'] = get_earliest_message(messages)
				ticket['first_response_score'] = get_first_response(ticket['created_at'], ticket['earliest_message'])
			except Exception as e:
				print(f"{e} - {ticket['case_id']}")

		set_assignee(tickets)
		set_group(tickets)

		spreadsheet, sheet, headers = create_tickets_table(client, tickets)

		for i, ticket in enumerate(tickets, start=2):
			data = ticket['messages']
			ai_result = make_request_ai(data)
			ticket['ai_result'] = ai_result
			update_table_with_ai_results(sheet, ticket, headers, i)

		return {"message": f"Successfully analyzed {len(tickets)} tickets"}
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
	import uvicorn
	uvicorn.run(app, host="0.0.0.0", port=8000)