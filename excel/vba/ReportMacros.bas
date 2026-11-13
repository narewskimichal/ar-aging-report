Attribute VB_Name = "ReportMacros"
Option Explicit

' Odœwie¿a zapytania Power Query i wszystkie tabele przestawne, a na arkuszu Summary wpisuje datê i godzinê odœwie¿enia.
Sub RefreshReport()
    Dim cn As WorkbookConnection
    Dim pc As PivotCache

    Application.ScreenUpdating = False

    ' wy³¹czenie odœwie¿ania w tle, ¿eby makro czeka³o na Power Query
    For Each cn In ThisWorkbook.Connections
        If cn.Type = xlConnectionTypeOLEDB Then cn.OLEDBConnection.BackgroundQuery = False
    Next cn

    ThisWorkbook.RefreshAll
    Application.CalculateUntilAsyncQueriesDone

    ' tabele przestawne odœwie¿ane dopiero po za³adowaniu nowych danych
    For Each pc In ThisWorkbook.PivotCaches
        pc.Refresh
    Next pc

    With ThisWorkbook.Worksheets("Summary").Range("B3")
        .Value = Now
        .NumberFormat = "dd.mm.yyyy hh:mm"
        .HorizontalAlignment = xlLeft
    End With

    Application.ScreenUpdating = True
    MsgBox "Raport odœwie¿ony. Miesi¹c raportu: " & _
        ThisWorkbook.Names("sel_month").RefersToRange.Value, vbInformation
End Sub

' Zapisuje arkusze Summary i Collections jako jeden plik PDF w folderze output obok pliku Excela
Sub ExportPDF()
    Dim folder As String
    Dim fileName As String

    folder = ThisWorkbook.Path & "\output"
    If Dir(folder, vbDirectory) = "" Then MkDir folder

    fileName = folder & "\AR_report_" & _
        ThisWorkbook.Names("sel_month").RefersToRange.Value & ".pdf"

    ThisWorkbook.Worksheets(Array("Summary", "Collections")).Select
    ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, fileName:=fileName, _
        Quality:=xlQualityStandard, IgnorePrintAreas:=False, OpenAfterPublish:=True
    ThisWorkbook.Worksheets("Summary").Select

    MsgBox "PDF zapisany: " & fileName, vbInformation
End Sub

