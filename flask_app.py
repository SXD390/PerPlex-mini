import os
import json
import logging
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
os.environ.setdefault("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

# Setup structured logging with rotation
def setup_logging():
    """Setup structured logging with rotation"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Setup file handler with rotation
    file_handler = RotatingFileHandler(
        'logs/perplex-lite.log', 
        maxBytes=2_000_000,  # 2MB
        backupCount=3
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s'
    ))
    
    # Setup console handler with Unicode support
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s'
    ))
    # Handle Unicode characters properly
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return root_logger

# Initialize logging
logger = setup_logging()

# Import our existing modules
from graph import build_app
from utils.conversation_manager import conversation_manager

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize LangGraph app
langgraph_app = build_app()

class ProcessingStatus:
    """Manages real-time processing status updates"""
    
    def __init__(self, socketio):
        self.socketio = socketio
        self.status_messages = {
            'thinking': '🤔 Analyzing your query and planning search strategy...',
            'searching': '🔍 Searching online for relevant information...',
            'distilling': '⚗️ Filtering and distilling search results...',
            'synthesizing': '📝 Synthesizing comprehensive response...',
            'qa_evaluating': '🔍 Quality checking response...',
            'reformatting': '✨ Improving response formatting...',
            'complete': '✅ Response ready!'
        }
    
    def emit_status(self, conversation_id, status, data=None):
        """Emit status update to client"""
        message = self.status_messages.get(status, status)
        
        # Create detailed status message based on data
        detailed_message = self._create_detailed_message(status, data)
        
        self.socketio.emit('processing_status', {
            'conversation_id': conversation_id,
            'status': status,
            'message': detailed_message,
            'data': data or {},
            'timestamp': datetime.now().isoformat()
        }, room=conversation_id)
        logger.info(f"Status update for {conversation_id}: {status} - {detailed_message}")
        logger.info(f"Emitted to room: {conversation_id}, data: {data}")
    
    def _create_detailed_message(self, status, data):
        """Create detailed status message based on status and data"""
        base_message = self.status_messages.get(status, status)
        
        if not data:
            return base_message
        
        if status == 'thinking':
            if data.get('elaborated_intent'):
                return f"🤔 Analyzing query: '{data.get('elaborated_intent', '')[:100]}...'"
            return base_message
            
        elif status == 'searching':
            if data.get('search_queries'):
                queries = data['search_queries']
                if len(queries) == 1:
                    return f"🔍 Searching: '{queries[0][:60]}...'"
                else:
                    return f"🔍 Searching {len(queries)} queries: '{queries[0][:40]}...' + {len(queries)-1} more"
            elif data.get('query_count'):
                return f"🔍 Executing {data['query_count']} search queries..."
            return base_message
            
        elif status == 'distilling':
            if data.get('raw_docs') and data.get('kept_docs'):
                return f"⚗️ Processing {data['raw_docs']} results → keeping {data['kept_docs']} relevant sources"
            return base_message
            
        elif status == 'synthesizing':
            if data.get('citations_count'):
                return f"📝 Synthesizing response with {data['citations_count']} citations..."
            return base_message
            
        elif status == 'qa_evaluating':
            if data.get('quality_score'):
                score = int(data['quality_score'] * 100)
                return f"🔍 Quality check: {score}% complete, evaluating response..."
            return base_message
            
        elif status == 'reformatting':
            if data.get('improvement_suggestions'):
                return f"✨ Improving formatting based on {len(data['improvement_suggestions'])} suggestions..."
            return base_message
            
        return base_message

# Global processing status manager
status_manager = ProcessingStatus(socketio)

@app.route('/')
def index():
    """Main chat interface"""
    return render_template('index.html')

@app.route('/api/conversations')
def get_conversations():
    """Get user's conversation history"""
    # For now, return all conversations regardless of user ID
    # This allows users to see all conversations
    conversations = conversation_manager.list_all_conversations(limit=50)
    return jsonify(conversations)

@app.route('/api/conversations/<conversation_id>')
def get_conversation(conversation_id):
    """Get specific conversation"""
    conversation = conversation_manager.get_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    return jsonify(conversation)

@app.route('/api/conversations/<conversation_id>/messages')
def get_conversation_messages(conversation_id):
    """Get messages for a conversation"""
    messages = conversation_manager.get_conversation_messages(conversation_id)
    return jsonify(messages)

@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    """Create a new conversation"""
    user_id = session.get('user_id', 'default')
    conversation_id = conversation_manager.create_conversation(user_id)
    session['current_conversation'] = conversation_id
    return jsonify({'conversation_id': conversation_id})

@app.route('/api/conversations/<conversation_id>/continue', methods=['POST'])
def continue_conversation(conversation_id):
    """Continue an existing conversation"""
    conversation_state = conversation_manager.continue_conversation(conversation_id)
    if not conversation_state:
        return jsonify({'error': 'Conversation not found'}), 404
    
    session['current_conversation'] = conversation_id
    return jsonify({'conversation_id': conversation_id, 'message_count': len(conversation_state['messages'])})

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Delete a conversation"""
    success = conversation_manager.delete_conversation(conversation_id)
    if success:
        return jsonify({'message': 'Conversation deleted successfully'})
    else:
        return jsonify({'error': 'Conversation not found'}), 404

@app.route('/api/conversations/<conversation_id>/status')
def get_conversation_status(conversation_id):
    """Get current analysis status for a conversation"""
    status = conversation_manager.get_analysis_status(conversation_id)
    if not status:
        return jsonify({'error': 'No active analysis found'}), 404
    return jsonify(status)

@app.route('/api/conversations/<conversation_id>/resume', methods=['POST'])
def resume_conversation(conversation_id):
    """Resume a conversation and get current status if analysis is active"""
    # Check if there's an active analysis
    is_active = conversation_manager.is_analysis_active(conversation_id)
    if is_active:
        status = conversation_manager.get_analysis_status(conversation_id)
        return jsonify({
            'conversation_id': conversation_id,
            'is_active': True,
            'status': status
        })
    else:
        return jsonify({
            'conversation_id': conversation_id,
            'is_active': False,
            'message': 'No active analysis'
        })

@app.route('/api/active-conversations')
def get_active_conversations():
    """Get list of conversations with active analysis"""
    active_conversations = conversation_manager.get_active_conversations()
    return jsonify({
        'active_conversations': active_conversations,
        'count': len(active_conversations)
    })

def process_query_async(conversation_id, user_query, user_id, mode='fast'):
    """Process query asynchronously with real-time updates"""
    try:
        # Start analysis tracking
        conversation_manager.start_analysis(conversation_id, user_query)
        
        # Emit thinking status
        status_manager.emit_status(conversation_id, 'thinking')
        
        # Load conversation history from the conversation manager
        conversation_history = conversation_manager.load_conversation_history(conversation_id)
        
        # Get current conversation state from LangGraph
        current_state = langgraph_app.get_state({"configurable": {"thread_id": f"web-{user_id}"}})
        current_messages = current_state.values.get("messages", []) if current_state.values else []
        
        # If we have conversation history, use it instead of the current state
        if conversation_history:
            current_messages = conversation_history
            logger.info(f"Loaded {len(conversation_history)} messages from conversation history for {conversation_id}")
        else:
            logger.info(f"No conversation history found for {conversation_id}, using current state")
        
        # Add new user message
        current_messages.append({"role": "user", "content": user_query})
        
        # Prepare processing metadata
        processing_metadata = {
            "start_time": datetime.now().isoformat(),
            "conversation_id": conversation_id
        }
        
        # Process through LangGraph with streaming and detailed status updates
        result = {}
        step_count = 0
        
        for chunk in langgraph_app.stream(
            {
                "messages": current_messages,
                "user_query": user_query,
                "iteration_count": 0,
                "conversation_id": conversation_id,
                "processing_metadata": processing_metadata,
                "mode": mode
            },
            config={"configurable": {"thread_id": f"web-{user_id}"}}
        ):
            # Extract the node name and data from the chunk
            for node_name, node_data in chunk.items():
                step_count += 1
                logger.info(f"Processing node: {node_name} (step {step_count})")
                
                # Handle None node_data
                if node_data is None:
                    logger.warning(f"Node {node_name} returned None data, skipping")
                    continue
                    
                logger.info(f"Node data keys: {list(node_data.keys())}")
                
                # Accumulate result data
                result.update(node_data)
                
                # Emit step start status
                status_manager.emit_status(conversation_id, 'processing', {
                    'step': step_count,
                    'node': node_name,
                    'message': f'Step {step_count}: Processing {node_name}...'
                })
                
                if node_name == "thinking":
                    status_manager.emit_status(conversation_id, 'thinking', {
                        'message': 'Analyzing your query and planning search strategy...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'thinking', step_count, {
                        'message': 'Analyzing your query and planning search strategy...'
                    })
                    
                    if node_data.get("thinking_result"):
                        thinking_result = node_data["thinking_result"]
                        elaborated_intent = thinking_result.get("elaborated_intent", "")
                        search_queries = thinking_result.get("search_queries", [])
                        needs_search = thinking_result.get("needs_web_search", False)
                        
                        logger.info(f"Thinking result: {elaborated_intent[:100]}...")
                        
                        if elaborated_intent:
                            status_manager.emit_status(conversation_id, 'thinking', {
                                'elaborated_intent': elaborated_intent,
                                'message': f'Analyzing: "{elaborated_intent[:80]}..."'
                            })
                            conversation_manager.update_analysis_status(conversation_id, 'thinking', step_count, {
                                'elaborated_intent': elaborated_intent,
                                'message': f'Analyzing: "{elaborated_intent[:80]}..."'
                            })
                        
                        if needs_search and search_queries:
                            status_manager.emit_status(conversation_id, 'searching', {
                                'search_queries': search_queries,
                                'query_count': len(search_queries),
                                'message': f'Planning {len(search_queries)} search queries...'
                            })
                            conversation_manager.update_analysis_status(conversation_id, 'searching', step_count, {
                                'search_queries': search_queries,
                                'query_count': len(search_queries),
                                'message': f'Planning {len(search_queries)} search queries...'
                            })
                        else:
                            status_manager.emit_status(conversation_id, 'searching', {
                                'message': 'No web search needed, using conversation context'
                            })
                
                elif node_name == "search":
                    status_manager.emit_status(conversation_id, 'searching', {
                        'message': 'Executing web search queries...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'searching', step_count, {
                        'message': 'Executing web search queries...'
                    })
                    
                    if node_data.get("raw_docs"):
                        raw_docs = node_data["raw_docs"]
                        logger.info(f"Search found {len(raw_docs)} documents")
                        status_manager.emit_status(conversation_id, 'searching', {
                            'message': f'Found {len(raw_docs)} search results from web search'
                        })
                        conversation_manager.update_analysis_status(conversation_id, 'searching', step_count, {
                            'message': f'Found {len(raw_docs)} search results from web search',
                            'raw_docs_count': len(raw_docs)
                        })
                
                elif node_name == "distiller":
                    status_manager.emit_status(conversation_id, 'distilling', {
                        'message': 'Filtering and distilling search results...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'distilling', step_count, {
                        'message': 'Filtering and distilling search results...'
                    })
                    
                    if node_data.get("distiller_result"):
                        distiller_result = node_data["distiller_result"]
                        raw_docs = distiller_result.get('total_original_docs', 0)
                        filtered_docs = distiller_result.get('filtered_out_count', 0)
                        kept_docs = len(distiller_result.get('distilled_docs', []))
                        
                        logger.info(f"Distiller result: {raw_docs} raw → {kept_docs} kept")
                        status_manager.emit_status(conversation_id, 'distilling', {
                            'raw_docs': raw_docs,
                            'filtered_docs': filtered_docs,
                            'kept_docs': kept_docs,
                            'message': f'Processing {raw_docs} results → keeping {kept_docs} relevant sources'
                        })
                        conversation_manager.update_analysis_status(conversation_id, 'distilling', step_count, {
                            'raw_docs': raw_docs,
                            'filtered_docs': filtered_docs,
                            'kept_docs': kept_docs,
                            'message': f'Processing {raw_docs} results → keeping {kept_docs} relevant sources'
                        })
                
                elif node_name == "synthesize":
                    status_manager.emit_status(conversation_id, 'synthesizing', {
                        'message': 'Synthesizing comprehensive response...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'synthesizing', step_count, {
                        'message': 'Synthesizing comprehensive response...'
                    })
                    
                    if node_data.get("answer"):
                        citations_count = len(node_data.get("citations", []))
                        answer_length = len(node_data.get("answer", ""))
                        logger.info(f"Synthesize result: {citations_count} citations, {answer_length} chars")
                        status_manager.emit_status(conversation_id, 'synthesizing', {
                            'citations_count': citations_count,
                            'answer_length': answer_length,
                            'message': f'Creating comprehensive response with {citations_count} citations ({answer_length} characters)'
                        })
                        conversation_manager.update_analysis_status(conversation_id, 'synthesizing', step_count, {
                            'citations_count': citations_count,
                            'answer_length': answer_length,
                            'message': f'Creating comprehensive response with {citations_count} citations ({answer_length} characters)'
                        })
                
                elif node_name == "qa_agent":
                    status_manager.emit_status(conversation_id, 'qa_evaluating', {
                        'message': 'Quality checking response...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'qa_evaluating', step_count, {
                        'message': 'Quality checking response...'
                    })

                    if node_data.get("qa_result"):
                        qa_result = node_data["qa_result"]
                        quality_score = qa_result.get('quality_score', 0.0)
                        needs_more_data = qa_result.get('needs_more_data', False)
                        should_reformat = qa_result.get('should_reformat', False)

                        logger.info(f"QA result: quality={quality_score}, needs_more={needs_more_data}, reformat={should_reformat}")
                        status_manager.emit_status(conversation_id, 'qa_evaluating', {
                            'quality_score': quality_score,
                            'needs_more_data': needs_more_data,
                            'should_reformat': should_reformat,
                            'message': f'Quality check: {int(quality_score * 100)}% complete'
                        })

                elif node_name == "formatter":
                    status_manager.emit_status(conversation_id, 'formatting', {
                        'message': 'Formatting response and adding citations...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'formatting', step_count, {
                        'message': 'Formatting response and adding citations...'
                    })

                    if node_data.get("formatter_result"):
                        formatter_result = node_data["formatter_result"]
                        formatting_applied = formatter_result.get('formatting_applied', False)
                        citation_count = formatter_result.get('citation_count', 0)

                        logger.info(f"Formatter result: formatting_applied={formatting_applied}, citations={citation_count}")
                        status_manager.emit_status(conversation_id, 'formatting', {
                            'formatting_applied': formatting_applied,
                            'citation_count': citation_count,
                            'message': f'Formatting complete: {citation_count} citations added'
                        })
                
                elif node_name == "reformat":
                    status_manager.emit_status(conversation_id, 'reformatting', {
                        'message': 'Improving response formatting...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'reformatting', step_count, {
                        'message': 'Improving response formatting...'
                    })
                    
                    if node_data.get("answer"):
                        logger.info("Reformat completed")
                        status_manager.emit_status(conversation_id, 'reformatting', {
                            'message': 'Response formatting improved successfully'
                        })
                        conversation_manager.update_analysis_status(conversation_id, 'reformatting', step_count, {
                            'message': 'Response formatting improved successfully'
                        })
                
                elif node_name == "title_agent":
                    status_manager.emit_status(conversation_id, 'processing', {
                        'message': 'Generating conversation title...'
                    })
                    conversation_manager.update_analysis_status(conversation_id, 'processing', step_count, {
                        'message': 'Generating conversation title...'
                    })
                    
                    if node_data.get("conversation_title"):
                        title = node_data["conversation_title"]
                        logger.info(f"Generated title: {title}")
                        status_manager.emit_status(conversation_id, 'processing', {
                            'message': f'Generated title: "{title}"'
                        })
                        conversation_manager.update_analysis_status(conversation_id, 'processing', step_count, {
                            'message': f'Generated title: "{title}"',
                            'conversation_title': title
                        })
        
        # Check if we have a valid result
        if not result:
            logger.error("No result from LangGraph processing")
            status_manager.emit_status(conversation_id, 'error', {
                'error': 'No result from processing',
                'message': 'Processing completed but no result was returned.'
            })
            conversation_manager.update_analysis_status(conversation_id, 'error', step_count, {
                'error': 'No result from processing',
                'message': 'Processing completed but no result was returned.'
            }, error='No result from processing')
            return
        
        # Extract the final answer safely (use formatter output if available)
        formatter_result = result.get("formatter_result", {})
        if formatter_result and formatter_result.get("formatted_answer"):
            final_answer = formatter_result["formatted_answer"]
            citations = formatter_result.get("citations", [])
        else:
            final_answer = result.get("answer", "")
            citations = result.get("citations", [])
        conversation_title = result.get("conversation_title")
        
        if not final_answer:
            logger.error("No answer in result")
            status_manager.emit_status(conversation_id, 'error', {
                'error': 'No answer generated',
                'message': 'Processing completed but no answer was generated.'
            })
            conversation_manager.update_analysis_status(conversation_id, 'error', step_count, {
                'error': 'No answer generated',
                'message': 'Processing completed but no answer was generated.'
            }, error='No answer generated')
            return
        
        # Prepare comprehensive processing metadata for logging
        full_processing_metadata = conversation_manager.prepare_processing_metadata(result)
        
        # Log the complete conversation turn
        conversation_manager.log_conversation_turn(
            conversation_id=conversation_id,
            user_query=user_query,
            assistant_response=final_answer,
            citations=citations,
            processing_metadata=full_processing_metadata,
            conversation_title=conversation_title
        )
        
        # Mark analysis as completed
        conversation_manager.complete_analysis(conversation_id, {
            'response': final_answer,
            'citations': citations,
            'processing_metadata': full_processing_metadata
        })
        
        # Emit complete status with final response
        status_manager.emit_status(conversation_id, 'complete', {
            'response': final_answer,
            'citations': citations,
            'processing_metadata': full_processing_metadata
        })
        
        # Emit the final assistant response
        socketio.emit('assistant_response', {
            'conversation_id': conversation_id,
            'response': final_answer,
            'citations': citations,
            'timestamp': datetime.now().isoformat()
        }, room=conversation_id)
        
        logger.info(f"Emitted assistant response for conversation {conversation_id}")
        
        logger.info(f"Completed processing for conversation {conversation_id}")
        
    except Exception as e:
        logger.error(f"Error processing query for {conversation_id}: {str(e)}")
        status_manager.emit_status(conversation_id, 'error', {
            'error': str(e),
            'message': 'An error occurred while processing your request.'
        })
        conversation_manager.update_analysis_status(conversation_id, 'error', step_count, {
            'error': str(e),
            'message': 'An error occurred while processing your request.'
        }, error=str(e))

@socketio.on('send_message')
def handle_message(data):
    """Handle incoming chat messages"""
    conversation_id = data.get('conversation_id')
    user_query = data.get('message', '').strip()
    mode = data.get('mode', 'fast')  # Default to fast mode
    user_id = session.get('user_id', 'default')
    
    if not user_query:
        return
    
    if not conversation_id:
        # Create new conversation
        conversation_id = conversation_manager.create_conversation(user_id)
        session['current_conversation'] = conversation_id
        emit('conversation_created', {'conversation_id': conversation_id})
    
    # Join the conversation room for real-time updates
    join_room(conversation_id)
    
    # Emit user message immediately to UI
    emit('user_message', {
        'conversation_id': conversation_id,
        'message': user_query,
        'timestamp': datetime.now().isoformat()
    }, room=conversation_id)
    
    # Start processing in background thread
    thread = threading.Thread(
        target=process_query_async,
        args=(conversation_id, user_query, user_id, mode)
    )
    thread.daemon = True
    thread.start()

@socketio.on('join_conversation')
def handle_join_conversation(data):
    """Join a conversation room for real-time updates"""
    conversation_id = data.get('conversation_id')
    if conversation_id:
        join_room(conversation_id)
        logger.info(f"Joined conversation room: {conversation_id}")
        
        # Check if there's an active analysis and replay status history
        if conversation_manager.is_analysis_active(conversation_id):
            status = conversation_manager.get_analysis_status(conversation_id)
            if status:
                # Replay the status history to show the user what's happened so far
                status_history = conversation_manager.get_analysis_status_history(conversation_id)
                logger.info(f"Replaying {len(status_history)} status updates for {conversation_id}")
                
                # Send each status update with a small delay to simulate the waterfall effect
                for i, status_entry in enumerate(status_history):
                    # Use a small delay to create the waterfall effect
                    time.sleep(0.1)  # 100ms delay between each status update
                    
                    socketio.emit('processing_status', {
                        'conversation_id': conversation_id,
                        'status': status_entry['status'],
                        'message': status_entry.get('data', {}).get('message', 'Processing...'),
                        'data': status_entry.get('data', {}),
                        'timestamp': status_entry.get('timestamp', datetime.now().isoformat()),
                        'is_replay': True  # Flag to indicate this is a replay
                    }, room=conversation_id)
                
                # Send the current status as the final update
                socketio.emit('processing_status', {
                    'conversation_id': conversation_id,
                    'status': status['status'],
                    'message': status.get('current_data', {}).get('message', 'Analysis in progress...'),
                    'data': status.get('current_data', {}),
                    'timestamp': status.get('last_updated', datetime.now().isoformat()),
                    'is_replay': False  # This is the current status
                }, room=conversation_id)
                
                logger.info(f"Replayed status history and sent current status for {conversation_id}")
        else:
            logger.info(f"No active analysis for conversation {conversation_id}")

@socketio.on('request_status')
def handle_request_status(data):
    """Handle request for current analysis status"""
    conversation_id = data.get('conversation_id')
    if conversation_id:
        if conversation_manager.is_analysis_active(conversation_id):
            status = conversation_manager.get_analysis_status(conversation_id)
            if status:
                # Send to the room so all clients in that conversation get the update
                socketio.emit('processing_status', {
                    'conversation_id': conversation_id,
                    'status': status['status'],
                    'message': status.get('current_data', {}).get('message', 'Analysis in progress...'),
                    'data': status.get('current_data', {}),
                    'timestamp': status.get('last_updated', datetime.now().isoformat())
                }, room=conversation_id)
                logger.info(f"Sent current status for {conversation_id} to room")
        else:
            # Send idle status to the room
            socketio.emit('processing_status', {
                'conversation_id': conversation_id,
                'status': 'idle',
                'message': 'No active analysis',
                'data': {},
                'timestamp': datetime.now().isoformat()
            }, room=conversation_id)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    # Generate or get user ID
    if 'user_id' not in session:
        session['user_id'] = f"user_{int(time.time())}"
    
    logger.info(f"Client connected: {session['user_id']}")
    emit('connected', {'user_id': session['user_id']})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {session.get('user_id', 'unknown')}")

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Run the Flask app
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
