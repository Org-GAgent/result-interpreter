import sys
import os

# Ensure we can import from app
sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv()

from app.database import init_db
from app.repository.plan_repository import PlanRepository

if __name__ == '__main__':
    init_db()
    
    repo = PlanRepository()
    print("Creating Plan...")
    plan_tree = repo.create_plan("Test Plan", description="This is a test plan.")
    print(f"Created Plan: {plan_tree.id} - {plan_tree.title}")
    
    print("Listing Plans:")
    plans = repo.list_plans()
    for p in plans:
        print(f" - {p.id}: {p.title}")