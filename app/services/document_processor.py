"""
Document Processing Service
Handles async document verification and processing
"""

import logging
import hashlib
import requests
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.landlord_onboarding import DocumentProcessingJob, LandlordOnboarding
from ..schemas.landlord_onboarding import DocumentProcessingJobResponse

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Service for processing verification documents"""
    
    def __init__(self):
        self.ocr_service_url = "https://api.ocr.service.com/v1/extract"  # Replace with actual OCR service
        self.verification_service_url = "https://api.verification.service.com/v1/verify"  # Replace with actual verification service
    
    async def process_document_async(
        self,
        onboarding_id: UUID,
        document_type: str,
        document_url: str,
        job_id: Optional[UUID] = None
    ):
        """Process document asynchronously"""
        logger.info(f"Processing {document_type} document for onboarding: {onboarding_id}")
        
        db = SessionLocal()
        try:
            # Create or update processing job
            if job_id:
                job = db.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.id == job_id
                ).first()
            else:
                # Check for existing job with same content
                content_hash = await self._generate_content_hash(document_url)
                existing_job = db.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.content_hash == content_hash,
                    DocumentProcessingJob.job_status.in_(['completed', 'processing'])
                ).first()
                
                if existing_job:
                    logger.info(f"Document already processed: {existing_job.id}")
                    return existing_job
                
                # Create new job
                job = DocumentProcessingJob(
                    onboarding_id=onboarding_id,
                    document_type=document_type,
                    document_url=document_url,
                    content_hash=content_hash,
                    job_status='queued'
                )
                db.add(job)
                db.flush()
            
            # Start processing
            job.job_status = 'processing'
            job.started_at = func.now()
            db.commit()
            
            # Process based on document type
            result = await self._process_by_type(document_type, document_url, job)
            
            # Update job with results
            job.job_status = result['status']
            job.extraction_results = result.get('extraction_results')
            job.verification_results = result.get('verification_results')
            job.confidence_score = result.get('confidence_score', 0)
            job.error_message = result.get('error_message')
            
            if result['status'] == 'completed':
                job.completed_at = func.now()
                await self._update_onboarding_document_status(onboarding_id, document_type, result, db)
            elif result['status'] == 'failed' and job.retry_count < job.max_retries:
                # Retry logic
                job.retry_count += 1
                job.job_status = 'retrying'
                logger.info(f"Retrying document processing (attempt {job.retry_count}): {job.id}")
                # Schedule retry (you might use Celery or similar for this)
                # await self.schedule_retry(job.id)
            
            db.commit()
            logger.info(f"Document processing completed: {job.id} - {job.job_status}")
            
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            if job:
                job.job_status = 'failed'
                job.error_message = str(e)
                db.commit()
        finally:
            db.close()
    
    async def _process_by_type(self, document_type: str, document_url: str, job: DocumentProcessingJob) -> Dict[str, Any]:
        """Process document based on type"""
        try:
            if document_type in ['nin', 'bvn', 'id_document']:
                return await self._process_identity_document(document_type, document_url)
            elif document_type == 'selfie':
                return await self._process_selfie_document(document_url)
            elif document_type == 'bank_statement':
                return await self._process_bank_statement(document_url)
            elif document_type in ['insurance', 'cac_certificate', 'guarantor_id']:
                return await self._process_supporting_document(document_type, document_url)
            else:
                raise ValueError(f"Unknown document type: {document_type}")
                
        except Exception as e:
            logger.error(f"Error processing {document_type}: {str(e)}")
            return {
                'status': 'failed',
                'error_message': str(e),
                'extraction_results': None,
                'verification_results': None,
                'confidence_score': 0
            }
    
    async def _process_identity_document(self, document_type: str, document_url: str) -> Dict[str, Any]:
        """Process NIN, BVN, or ID document"""
        logger.info(f"Processing identity document: {document_type}")
        
        # Extract text using OCR
        extraction_result = await self._extract_text_from_image(document_url)
        if not extraction_result['success']:
            return {
                'status': 'failed',
                'error_message': extraction_result['error'],
                'extraction_results': None,
                'verification_results': None,
                'confidence_score': 0
            }
        
        # Verify document based on type
        verification_result = await self._verify_identity_document(
            document_type, 
            extraction_result['extracted_text'],
            extraction_result['metadata']
        )
        
        return {
            'status': 'completed' if verification_result['verified'] else 'failed',
            'extraction_results': extraction_result,
            'verification_results': verification_result,
            'confidence_score': verification_result.get('confidence_score', 0),
            'error_message': verification_result.get('error_message') if not verification_result['verified'] else None
        }
    
    async def _process_selfie_document(self, document_url: str) -> Dict[str, Any]:
        """Process selfie for face verification"""
        logger.info("Processing selfie document")
        
        # Face detection and verification
        verification_result = await self._verify_face_document(document_url)
        
        return {
            'status': 'completed' if verification_result['verified'] else 'failed',
            'extraction_results': None,
            'verification_results': verification_result,
            'confidence_score': verification_result.get('confidence_score', 0),
            'error_message': verification_result.get('error_message') if not verification_result['verified'] else None
        }
    
    async def _process_bank_statement(self, document_url: str) -> Dict[str, Any]:
        """Process bank statement for account verification"""
        logger.info("Processing bank statement")
        
        # Extract account information
        extraction_result = await self._extract_text_from_image(document_url)
        if not extraction_result['success']:
            return {
                'status': 'failed',
                'error_message': extraction_result['error'],
                'extraction_results': None,
                'verification_results': None,
                'confidence_score': 0
            }
        
        # Verify bank account
        verification_result = await self._verify_bank_account(
            extraction_result['extracted_text'],
            extraction_result['metadata']
        )
        
        return {
            'status': 'completed' if verification_result['verified'] else 'failed',
            'extraction_results': extraction_result,
            'verification_results': verification_result,
            'confidence_score': verification_result.get('confidence_score', 0),
            'error_message': verification_result.get('error_message') if not verification_result['verified'] else None
        }
    
    async def _process_supporting_document(self, document_type: str, document_url: str) -> Dict[str, Any]:
        """Process supporting documents (insurance, CAC, guarantor ID)"""
        logger.info(f"Processing supporting document: {document_type}")
        
        # Extract text for validation
        extraction_result = await self._extract_text_from_image(document_url)
        
        return {
            'status': 'completed',
            'extraction_results': extraction_result,
            'verification_results': {
                'verified': True,
                'document_type': document_type,
                'validation_passed': extraction_result['success']
            },
            'confidence_score': extraction_result.get('confidence', 85),
            'error_message': None
        }
    
    async def _extract_text_from_image(self, image_url: str) -> Dict[str, Any]:
        """Extract text from image using OCR service"""
        try:
            # Call OCR service
            response = requests.post(
                self.ocr_service_url,
                json={'image_url': image_url},
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                'success': True,
                'extracted_text': result.get('text', ''),
                'metadata': {
                    'confidence': result.get('confidence', 0),
                    'processing_time': result.get('processing_time', 0),
                    'language': result.get('language', 'eng')
                }
            }
            
        except requests.RequestException as e:
            logger.error(f"OCR service error: {str(e)}")
            return {
                'success': False,
                'error': f"OCR service unavailable: {str(e)}",
                'extracted_text': '',
                'metadata': {}
            }
    
    async def _verify_identity_document(self, document_type: str, extracted_text: str, metadata: Dict) -> Dict[str, Any]:
        """Verify identity document with government services"""
        try:
            # Mock verification - replace with actual government API calls
            if document_type == 'nin':
                # Call NIN verification service
                verification_result = await self._verify_nin(extracted_text)
            elif document_type == 'bvn':
                # Call BVN verification service
                verification_result = await self._verify_bvn(extracted_text)
            else:
                # Generic ID verification
                verification_result = await self._verify_id_document(extracted_text, metadata)
            
            return verification_result
            
        except Exception as e:
            logger.error(f"Identity verification error: {str(e)}")
            return {
                'verified': False,
                'error_message': str(e),
                'confidence_score': 0
            }
    
    async def _verify_face_document(self, image_url: str) -> Dict[str, Any]:
        """Verify face in selfie document"""
        try:
            # Call face verification service
            response = requests.post(
                f"{self.verification_service_url}/face",
                json={'image_url': image_url},
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                'verified': result.get('face_detected', False),
                'confidence_score': result.get('confidence', 0),
                'face_count': result.get('face_count', 0),
                'liveness_detected': result.get('liveness_detected', False),
                'error_message': result.get('error_message')
            }
            
        except requests.RequestException as e:
            logger.error(f"Face verification error: {str(e)}")
            return {
                'verified': False,
                'error_message': str(e),
                'confidence_score': 0
            }
    
    async def _verify_bank_account(self, extracted_text: str, metadata: Dict) -> Dict[str, Any]:
        """Verify bank account from statement"""
        try:
            # Extract account details from text
            account_details = self._parse_bank_statement(extracted_text)
            
            # Call bank verification API
            response = requests.post(
                f"{self.verification_service_url}/bank",
                json=account_details,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                'verified': result.get('account_valid', False),
                'confidence_score': result.get('confidence', 0),
                'account_name': result.get('account_name'),
                'bank_name': result.get('bank_name'),
                'error_message': result.get('error_message')
            }
            
        except Exception as e:
            logger.error(f"Bank verification error: {str(e)}")
            return {
                'verified': False,
                'error_message': str(e),
                'confidence_score': 0
            }
    
    def _parse_bank_statement(self, text: str) -> Dict[str, Any]:
        """Parse bank statement text to extract account details"""
        # Mock parsing - implement actual parsing logic
        import re
        
        account_number = None
        account_name = None
        bank_name = None
        
        # Extract account number (mock pattern)
        account_match = re.search(r'Account\s*No\.?\s*:?\s*(\d{10})', text, re.IGNORECASE)
        if account_match:
            account_number = account_match.group(1)
        
        # Extract account name (mock pattern)
        name_match = re.search(r'Account\s*Name\s*:?\s*([A-Z\s]+)', text, re.IGNORECASE)
        if name_match:
            account_name = name_match.group(1).strip()
        
        return {
            'account_number': account_number,
            'account_name': account_name,
            'bank_name': bank_name,
            'statement_text': text
        }
    
    async def _verify_nin(self, extracted_text: str) -> Dict[str, Any]:
        """Verify NIN with government service"""
        # Mock implementation - replace with actual NIN verification API
        nin_pattern = r'\b\d{11}\b'
        nin_match = re.search(nin_pattern, extracted_text)
        
        if nin_match:
            nin = nin_match.group(0)
            # Call actual NIN verification service here
            return {
                'verified': True,  # Mock - should be actual verification result
                'confidence_score': 95,
                'nin': nin,
                'name': 'Verified Name',  # Should come from API
                'error_message': None
            }
        
        return {
            'verified': False,
            'error_message': 'NIN not found in document',
            'confidence_score': 0
        }
    
    async def _verify_bvn(self, extracted_text: str) -> Dict[str, Any]:
        """Verify BVN with bank service"""
        # Mock implementation - replace with actual BVN verification API
        bvn_pattern = r'\b\d{11}\b'
        bvn_match = re.search(bvn_pattern, extracted_text)
        
        if bvn_match:
            bvn = bvn_match.group(0)
            # Call actual BVN verification service here
            return {
                'verified': True,  # Mock - should be actual verification result
                'confidence_score': 95,
                'bvn': bvn,
                'bank_name': 'Verified Bank',  # Should come from API
                'error_message': None
            }
        
        return {
            'verified': False,
            'error_message': 'BVN not found in document',
            'confidence_score': 0
        }
    
    async def _verify_id_document(self, extracted_text: str, metadata: Dict) -> Dict[str, Any]:
        """Verify generic ID document"""
        # Mock implementation
        return {
            'verified': True,
            'confidence_score': metadata.get('confidence', 85),
            'document_type': 'id_card',
            'error_message': None
        }
    
    async def _generate_content_hash(self, document_url: str) -> str:
        """Generate content hash for document deduplication"""
        try:
            # Download document content
            response = requests.get(document_url, timeout=30)
            response.raise_for_status()
            
            # Generate hash
            content_hash = hashlib.sha256(response.content).hexdigest()
            return content_hash
            
        except Exception as e:
            logger.error(f"Error generating content hash: {str(e)}")
            return hashlib.sha256(document_url.encode()).hexdigest()
    
    async def _update_onboarding_document_status(
        self, 
        onboarding_id: UUID, 
        document_type: str, 
        result: Dict[str, Any], 
        db: Session
    ):
        """Update onboarding document verification status"""
        onboarding = db.query(LandlordOnboarding).filter(
            LandlordOnboarding.id == onboarding_id
        ).first()
        
        if not onboarding:
            logger.error(f"Onboarding not found: {onboarding_id}")
            return
        
        # Update specific document verification status
        if document_type == 'nin':
            onboarding.nin_verified = result['verification_results'].get('verified', False)
        elif document_type == 'bvn':
            onboarding.bvn_verified = result['verification_results'].get('verified', False)
        elif document_type == 'id_document':
            onboarding.id_document_verified = result['verification_results'].get('verified', False)
        elif document_type == 'selfie':
            onboarding.selfie_verified = result['verification_results'].get('verified', False)
        elif document_type == 'bank_statement':
            onboarding.bank_verification_status = 'verified' if result['verification_results'].get('verified') else 'failed'
        
        # Update overall document processing status
        all_jobs = db.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.onboarding_id == onboarding_id
        ).all()
        
        completed_jobs = [job for job in all_jobs if job.job_status == 'completed']
        failed_jobs = [job for job in all_jobs if job.job_status == 'failed']
        
        if len(completed_jobs) == len(all_jobs):
            onboarding.document_processing_status = 'completed'
        elif len(failed_jobs) > 0:
            onboarding.document_processing_status = 'failed'
        else:
            onboarding.document_processing_status = 'processing'
        
        db.commit()
        logger.info(f"Updated document status for onboarding: {onboarding_id}")


# Global instance
document_processor = DocumentProcessor()


# Async function for background tasks
async def process_document_async(
    onboarding_id: UUID,
    document_type: str,
    document_url: str,
    job_id: Optional[UUID] = None
):
    """Async wrapper for document processing"""
    await document_processor.process_document_async(
        onboarding_id, document_type, document_url, job_id
    )
