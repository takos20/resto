# sync/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from globals.pagination import CustomPagination
from sync.filters import SyncConfigFilter, SyncLogFilter
from sync.models import SyncConfig, SyncLog
from .sync_service import SyncService
from .serializers import SyncLogSerializer, SyncConfigSerializer
from rest_framework.permissions import AllowAny, IsAuthenticated, DjangoModelPermissions
from rest_framework.renderers import JSONRenderer
from django_filters import rest_framework as filters

class SyncViewSet(viewsets.ModelViewSet):
    """API pour la synchronisation"""
    queryset = SyncConfig.objects.all()
    serializer_class = SyncConfigSerializer
    renderer_classes = [JSONRenderer]
    permission_classes = (IsAuthenticated, DjangoModelPermissions)
    pagination_class = CustomPagination
    filterset_class = SyncConfigFilter
    filter_backends = (filters.DjangoFilterBackend,)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        permission_class = [IsAuthenticated]
        if self.action in ['upload', 'download', 'full_sync']:
            permission_class = [AllowAny]
        return [permission() for permission in permission_class]
    
    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        """Lancer une synchronisation upload (local → remote)"""
        hospital_id = request.data.get('hospital_id')
        force = request.data.get('force', False)
        
        if not hospital_id:
            return Response(
                {'error': 'hospital_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            sync_service = SyncService(hospital_id)
            results = sync_service.upload_changes(force=force)
            
            return Response({
                'message': 'Upload terminé',
                'results': results
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='download')
    def download(self, request):
        """Lancer une synchronisation download (remote → local)"""
        hospital_id = request.data.get('hospital_id')
        force = request.data.get('force', False)
        
        if not hospital_id:
            return Response(
                {'error': 'hospital_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            sync_service = SyncService(hospital_id)
            results = sync_service.download_changes(force=force)
            
            return Response({
                'message': 'Download terminé',
                'results': results
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='full_sync')
    def full_sync(self, request):
        """Synchronisation complète (bidirectionnelle)"""
        hospital_id = request.data.get('hospital_id')
        
        if not hospital_id:
            return Response(
                {'error': 'hospital_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            sync_service = SyncService(hospital_id)
            
            # Upload puis Download
            upload_results = sync_service.upload_changes(force=True)
            download_results = sync_service.download_changes(force=True)
            
            return Response({
                'message': 'Synchronisation complète terminée',
                'upload': upload_results,
                'download': download_results,
                'status': sync_service.get_sync_status()
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """Obtenir le statut de synchronisation"""
        hospital_id = request.query_params.get('hospital_id')
        
        if not hospital_id:
            return Response(
                {'error': 'hospital_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            sync_service = SyncService(hospital_id)
            sync_status = sync_service.get_sync_status()
            
            return Response(sync_status)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def conflicts(self, request):
        """Lister les conflits de synchronisation"""
        hospital_id = request.query_params.get('hospital_id')
        
        if not hospital_id:
            return Response(
                {'error': 'hospital_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from .models import SyncLog
        
        conflicts = SyncLog.objects.filter(
            hospital_id=hospital_id,
            status='CONFLICT'
        ).order_by('-createdAt')
        
        serializer = SyncLogSerializer(conflicts, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def resolve_conflict(self, request, pk=None):
        """Résoudre un conflit manuellement"""
        from .models import SyncLog
        
        resolution = request.data.get('resolution')  # 'LOCAL_WINS' ou 'REMOTE_WINS'
        
        if resolution not in ['LOCAL_WINS', 'REMOTE_WINS']:
            return Response(
                {'error': 'resolution invalide'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            sync_log = SyncLog.objects.get(pk=pk, status='CONFLICT')
            
            sync_service = SyncService(sync_log.hospital_id)
            
            if resolution == 'LOCAL_WINS':
                sync_service._resend_local_data(sync_log)
            else:
                sync_service._apply_remote_data(sync_log, sync_log.data_snapshot)
            
            return Response({'message': 'Conflit résolu'})
            
        except SyncLog.DoesNotExist:
            return Response(
                {'error': 'SyncLog introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

class SyncLogViewSet(viewsets.ViewSet):
    queryset = SyncLog.objects.all()
    serializer_class = SyncLogSerializer
    renderer_classes = [JSONRenderer]
    permission_classes = (IsAuthenticated, DjangoModelPermissions)
    pagination_class = CustomPagination
    filterset_class = SyncLogFilter
    filter_backends = (filters.DjangoFilterBackend,)