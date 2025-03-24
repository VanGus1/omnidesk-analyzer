from utils import get_tickets, get_messages, clean_message, role_count, set_assignee, set_group, get_earliest_message, make_request_ai, get_first_response, create_tickets_table, init_google_sheets, update_table_with_ai_results

def main():

	client = init_google_sheets()

	tickets = get_tickets(limit = 10, status = 'closed')
	
	for ticket in tickets:
		print(f'{ticket['case_id']}')
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
			print(f'{e} - {ticket['case_id']}')

	set_assignee(tickets)
	set_group(tickets)

	spreadsheet, sheet, headers = create_tickets_table(client, tickets)

	# for i, ticket in enumerate(tickets, start=2):
	# 	data = ticket['messages']
	# 	ai_result = make_request_ai(data)
	# 	ticket['ai_result'] = ai_result

	# 	update_table_with_ai_results(sheet, ticket, headers, i)


if __name__ == '__main__':
	main()