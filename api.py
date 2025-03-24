from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uvicorn
from utils import get_tickets, get_messages, clean_message, role_count, set_assignee, set_group, get_earliest_message, get_first_response, create_tickets_table, init_google_sheets, update_table_with_ai_results, make_request_ai

app = FastAPI(
    title="OmniDesk Analyzer API",
    description="API для анализа обращений OmniDesk",
    version="1.0.0"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TicketResponse(BaseModel):
    case_id: int
    case_number: str
    link: str
    staff_count: int
    user_count: int
    first_response_score: float
    assignee: str
    group: str
    created_at: datetime
    status: str
    rating: Optional[int]

class AnalysisRequest(BaseModel):
    limit: Optional[int] = 10
    status: Optional[str] = 'closed'
    use_ai: Optional[bool] = False

@app.get("/")
async def root():
    return {"message": "OmniDesk Analyzer API is running"}

@app.post("/analyze", response_model=List[TicketResponse])
async def analyze_tickets(request: AnalysisRequest):
    try:
        # Инициализация Google Sheets
        client = init_google_sheets()
        
        # Получение тикетов
        tickets = get_tickets(limit=request.limit, status=request.status)
        
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
                
                if request.use_ai:
                    ai_result = make_request_ai(messages)
                    ticket['ai_result'] = ai_result
                    
            except Exception as e:
                print(f'{e} - {ticket["case_id"]}')
                continue
        
        set_assignee(tickets)
        set_group(tickets)
        
        # Создание таблицы и обновление результатов
        spreadsheet, sheet, headers = create_tickets_table(client, tickets)
        
        if request.use_ai:
            for i, ticket in enumerate(tickets, start=2):
                update_table_with_ai_results(sheet, ticket, headers, i)
        
        return tickets
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True) 