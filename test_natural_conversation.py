#!/usr/bin/env python3
"""
Test script to verify enhanced natural conversation behavior.
This script tests that the agent responds naturally to different types of queries.
"""

import asyncio
import json
from app.services.agent_orchestrator import agent_orchestrator


async def test_conversation_modes():
    """Test different conversation modes and natural responses."""
    
    test_cases = [
        {
            "name": "Generic Greeting",
            "message": "Hi, how are you?",
            "expected_mode": "conversational",
            "should_extract_data": False
        },
        {
            "name": "Who Am I Question",
            "message": "Hi who am I?",
            "expected_mode": "conversational", 
            "should_extract_data": False
        },
        {
            "name": "Information Question",
            "message": "What is term insurance?",
            "expected_mode": "informational",
            "should_extract_data": False
        },
        {
            "name": "Purchase Intent",
            "message": "I want to buy term insurance",
            "expected_mode": "onboarding",
            "should_extract_data": True
        },
        {
            "name": "Generic Coverage Question",
            "message": "How much coverage do I need?",
            "expected_mode": "informational",
            "should_extract_data": False
        }
    ]
    
    print("=== Testing Enhanced Natural Conversation ===\n")
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"{i}. Testing: {test_case['name']}")
        print(f"   Message: \"{test_case['message']}\"")
        
        try:
            # Create a new session for each test to avoid context interference
            response = await agent_orchestrator.handle_turn(
                session_id=None,  # New session each time
                user_message=test_case['message']
            )
            
            mode = response.get('metadata', {}).get('mode', 'unknown')
            extracted = response.get('metadata', {}).get('extracted', {})
            has_extracted_data = any(v for v in extracted.values() if v is not None)
            
            print(f"   Response Mode: {mode}")
            print(f"   Expected Mode: {test_case['expected_mode']}")
            print(f"   Response: {response['message'][:100]}...")
            print(f"   Data Extracted: {has_extracted_data}")
            print(f"   Expected Data Extraction: {test_case['should_extract_data']}")
            
            # Check if mode matches expectation
            mode_correct = mode == test_case['expected_mode']
            data_extraction_correct = has_extracted_data == test_case['should_extract_data']
            
            test_passed = mode_correct and data_extraction_correct
            
            print(f"   Result: {'✅ PASS' if test_passed else '❌ FAIL'}")
            
            if not mode_correct:
                print(f"   ❌ Mode mismatch: got '{mode}', expected '{test_case['expected_mode']}'")
            if not data_extraction_correct:
                print(f"   ❌ Data extraction mismatch: got {has_extracted_data}, expected {test_case['should_extract_data']}")
            
            results.append({
                "test": test_case['name'],
                "passed": test_passed,
                "mode": mode,
                "expected_mode": test_case['expected_mode'],
                "data_extracted": has_extracted_data,
                "expected_data_extraction": test_case['should_extract_data']
            })
            
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results.append({
                "test": test_case['name'],
                "passed": False,
                "error": str(e)
            })
        
        print()
    
    # Summary
    print("=== Test Results Summary ===")
    passed_tests = sum(1 for r in results if r.get('passed', False))
    total_tests = len(results)
    
    print(f"Tests Passed: {passed_tests}/{total_tests}")
    
    for result in results:
        status = "✅ PASS" if result.get('passed', False) else "❌ FAIL"
        print(f"  {status} {result['test']}")
        if 'error' in result:
            print(f"    Error: {result['error']}")
    
    if passed_tests == total_tests:
        print("\n🎉 All tests passed! The agent now handles conversations naturally.")
    else:
        print(f"\n⚠️  {total_tests - passed_tests} test(s) failed. The agent needs further improvement.")
    
    return passed_tests == total_tests


async def test_context_memory():
    """Test that the agent remembers context appropriately."""
    print("\n=== Testing Context Memory ===")
    
    # Use a fixed session ID to test memory
    session_id = "test-memory-session"
    
    # First, establish some context in onboarding mode
    print("1. Establishing context (onboarding)...")
    response1 = await agent_orchestrator.handle_turn(
        session_id=session_id,
        user_message="I want to buy term insurance. My name is John Doe and I'm 30 years old."
    )
    
    mode1 = response1.get('metadata', {}).get('mode', 'unknown')
    print(f"   Mode: {mode1}")
    print(f"   Response: {response1['message'][:100]}...")
    
    # Then ask a casual question to see if it remembers context
    print("\n2. Asking casual question with established context...")
    response2 = await agent_orchestrator.handle_turn(
        session_id=session_id,
        user_message="What's my name again?"
    )
    
    mode2 = response2.get('metadata', {}).get('mode', 'unknown')
    mentions_name = "john" in response2['message'].lower() or "doe" in response2['message'].lower()
    
    print(f"   Mode: {mode2}")
    print(f"   Response: {response2['message'][:150]}...")
    print(f"   Mentions Name: {mentions_name}")
    
    context_test_passed = mode2 in ["conversational", "informational"] and mentions_name
    print(f"   Result: {'✅ PASS' if context_test_passed else '❌ FAIL'}")
    
    return context_test_passed


if __name__ == "__main__":
    async def main():
        try:
            print("Starting natural conversation behavior tests...\n")
            
            # Test conversation modes
            modes_test = await test_conversation_modes()
            
            # Test context memory
            memory_test = await test_context_memory()
            
            print("\n=== Final Results ===")
            print(f"Conversation Modes: {'✅ PASS' if modes_test else '❌ FAIL'}")
            print(f"Context Memory: {'✅ PASS' if memory_test else '❌ FAIL'}")
            
            if modes_test and memory_test:
                print("\n🎉 All tests passed! The agent is now more natural and context-aware.")
            else:
                print("\n⚠️  Some tests failed. The agent needs further improvement.")
                
        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(main())