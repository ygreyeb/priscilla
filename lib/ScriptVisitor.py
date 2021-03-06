import sys
import ast
from typing import List
from collections import deque
from PLGLOBALS import PLGLOBALS
from common import add_no_repeat, get_spec_classname_by_classname, ELSE, ELIF, SQL, SQL_VAR, TYPE
from BaseVisitor import BaseVisitor, PKG_PLHELPER, PKG_PLCURSOR
from SqlVisitor import SqlVisitor

sys.path.append('./built')
from PlSqlParser import PlSqlParser

OPERATORS = {
    "=": ast.Eq,
    "!=": ast.NotEq,
    "<>": ast.NotEq,
    ">": ast.Gt,
    ">=": ast.GtE,
    "<": ast.Lt,
    "<=": ast.LtE,
    "+": ast.Add,
    "-": ast.Sub,
    "*": ast.Mult,
    "/": ast.Div
}

TYPE_PLTABLE = "PLTABLE"
TYPE_PLTABLE_OF = "PLTABLE_OF"
TYPE_PLRECORD = "PLRECORD"
PKG_PLGLOBALS = "PLGLOBALS"

class ScriptVisitor(BaseVisitor):
# pylint: disable=I0011,C0103

    def __init__(self):
        super().__init__()
        self.pkgs_calls_found = []
        self.vars_in_package = []
        self.vars_declared = []
        self.pkg_name: str = None

    def visitSql_script(self, ctx: PlSqlParser.Sql_scriptContext):
        body = self.visitChildren(ctx)
        add_no_repeat(self.pkgs_calls_found, [PKG_PLGLOBALS, PKG_PLHELPER, PKG_PLCURSOR])
        imports = self.create_imports()
        body = imports + body
        return ast.Module(
            body=body
        )

    def visitUnit_statement(self, ctx:PlSqlParser.Unit_statementContext):
        ret = self.visitChildren(ctx)
        for i, expr in enumerate(ret.copy()):
            if not isinstance(expr, ast.Expr):
                ret[i] = ast.Expr(value=expr)
        return ret

    def visitAnonymous_block(self, ctx: PlSqlParser.Anonymous_blockContext):
        return self.visitBody(ctx)

    def visitCreate_package(self, ctx: PlSqlParser.Create_packageContext):
        self.vars_declared = self.vars_in_package
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        name: str = ret.popleft().id
        if ret:
            label = ret[-1]
            if isinstance(label, ast.Name) and label.id == name:
                ret.pop()
        name = get_spec_classname_by_classname(name)
        body = ret
        for item in body:
            if isinstance(item, ast.Assign):
                add_no_repeat(self.vars_declared, item.targets[0].id)
        if not body:
            body.append(ast.Pass())
        return ast.ClassDef(
            name=name,
            body=body,
            decorator_list=[],
            bases=[]
        )

    def visitCreate_package_body(self, ctx: PlSqlParser.Create_package_bodyContext):
        self.pkg_name = name = ctx.package_name()[0].getText().upper()
        add_no_repeat(self.vars_declared, name)
        self.vars_in_package = self.vars_declared
        ret = self.visitChildren(ctx)
        spec_classname = get_spec_classname_by_classname(name)
        if ret:
            label = ret[-1]
            if isinstance(label, ast.Name) and label.id == name:
                ret.pop()
        body = ret[1:] # we already had the name
        for item in body:
            if isinstance(item, ast.FunctionDef):
                item.decorator_list.append(ast.Name(id="staticmethod"))
        return ast.ClassDef(
            name=name,
            body=body,
            decorator_list=[],
            bases=[ast.Name(id=spec_classname)]
        )

    def visitCreate_procedure_body(self, ctx: PlSqlParser.Create_procedure_bodyContext):
        return self.visitCreate_function_body(ctx)

    def visitCreate_function_body(self, ctx: PlSqlParser.Create_function_bodyContext):
        visitor = ScriptVisitor()
        # FIXME: the function being processed should be added to vars_declared too, in case of recursivity
        visitor.vars_declared = self.vars_declared.copy()
        ret = visitor.visitChildren(ctx)
        ret = deque(ret)
        name = ret.popleft()
        add_no_repeat(self.vars_declared, name.id)
        args = []
        for expr in list(ret):
            if isinstance(expr, ast.arg):
                args.append(expr)
            elif isinstance(expr, TYPE):
                pass
            else:
                continue
            ret.remove(expr)
        args = ast.arguments(
            args=args,
            defaults=[],
            vararg=None,
            kwarg=None
        )
        body = ret
        return ast.FunctionDef(
            name=name.id,
            args=args,
            body=body,
            decorator_list=[],
            returns=None
        )

    def visitFunction_spec(self, ctx: PlSqlParser.Function_specContext):
        return None

    def visitProcedure_spec(self, ctx: PlSqlParser.Procedure_specContext):
        return None

    def visitPragma_declaration(self, ctx: PlSqlParser.Pragma_declarationContext):
        if ctx.AUTONOMOUS_TRANSACTION():
            return ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=PKG_PLCURSOR),
                    attr="AUTONOMOUS_TRANSACTION"
                ),
                args=[],
                keywords=[]
            )
        return None

    def visitFunction_body(self, ctx: PlSqlParser.Function_bodyContext):
        return self.visitProcedure_body(ctx)

    def visitProcedure_body(self, ctx: PlSqlParser.Procedure_bodyContext):
        visitor = ScriptVisitor()
        visitor.pkg_name = self.pkg_name
        visitor.vars_in_package = self.vars_in_package
        ret = visitor.manual_visitProcedure_body(ctx)
        add_no_repeat(self.vars_declared, ret.name)
        add_no_repeat(self.pkgs_calls_found, visitor.pkgs_calls_found)
        return ret

    def manual_visitProcedure_body(self, ctx: PlSqlParser.Procedure_bodyContext):
        args_names: List[str] = [
            param.parameter_name().getText().upper()
            for param in ctx.parameter()
        ]
        add_no_repeat(self.vars_declared, args_names)
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        name: ast.Name = ret.popleft()
        args = []
        while True:
            arg = ret[0]
            if not isinstance(arg, ast.arg):
                break
            args.append(arg)
            ret.popleft()
        body = ret
        for item in list(body):
            if isinstance(item, TYPE):
                # is a function definition. this is the return type
                body.remove(item)
                break
        for i, item in enumerate(body):
            # everything has to be an expression?
            if isinstance(item, ast.Expr):
                continue
            body[i] = ast.Expr(value=item)
        args = ast.arguments(
            args=args,
            defaults=[],
            vararg=None,
            kwarg=None
        )
        return ast.FunctionDef(
            name=name.id,
            args=args,
            body=body,
            decorator_list=[],
            returns=None
        )

    def visitParameter(self, ctx: PlSqlParser.ParameterContext):
        ret = self.visitChildren(ctx)
        name, *_ = ret
        return ast.arg(
            arg=name,
            annotation=None
        )

    def visitBody(self, ctx: PlSqlParser.BodyContext):
        ret = self.visitChildren(ctx)
        exception_handlers = []
        for expr in ret.copy():
            if isinstance(expr, ast.ExceptHandler):
                exception_handlers.append(expr)
                ret.remove(expr)
        if ret:
            label = ret[-1]
            if isinstance(label, ast.Name):
                # a name alone? should be a label
                ret.pop()
        if exception_handlers:
            return ast.Try(
                body=ret,
                handlers=exception_handlers,
                orelse=[],
                finalbody=[]
            )
        return ret

    def visitTransaction_control_statements(self, ctx: PlSqlParser.Transaction_control_statementsContext):
        call = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=PKG_PLCURSOR),
                attr=None
            ),
            args=[],
            keywords=[]
        )
        if ctx.commit_statement():
            call.func.attr = "commit"
            return call
        elif ctx.rollback_statement():
            call.func.attr = "rollback"
            return call
        else:
            raise NotImplementedError(f"unimplemented Transaction_control_statements {ctx.getText()}")

    def visitRaise_statement(self, ctx: PlSqlParser.Raise_statementContext):
        ret = self.visitChildren(ctx)
        name = None
        if ret:
            name = ret[0]
        return ast.Raise(
            exc=name,
            cause=None
        )

    def visitException_handler(self, ctx: PlSqlParser.Exception_handlerContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        exception = ret.popleft()
        body = list(ret)
        return ast.ExceptHandler(
            type=exception,
            body=body,
            name=None
        )

    def visitException_name(self, ctx: PlSqlParser.Exception_nameContext):
        ret: List[ast.Name] = self.visitChildren(ctx)
        excep = [item.id for item in ret]
        excep = self.wrap_recursive_properties(excep)
        return [excep]

    def visitStatement(self, ctx: PlSqlParser.StatementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        statement = ret.popleft()
        return ast.Expr(value=statement)

    def visitLoop_statement(self, ctx: PlSqlParser.Loop_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        if ctx.label_declaration():
            ret.popleft()
            ret.pop()
        expr = ast.While(
            test=ast.NameConstant(value=True),
            body=[],
            orelse=[]
        )
        if ctx.WHILE():
            expr.test = ret.popleft()
        elif ctx.FOR():
            expr = ret.popleft()
        expr.body = list(ret)
        return expr

    def visitCursor_loop_param(self, ctx: PlSqlParser.Cursor_loop_paramContext):
        target = ctx.index_name().getText().upper()
        # declare the variable for being recognized by the children
        add_no_repeat(self.vars_declared, target)
        ret = self.visitChildren(ctx)
        target, lower, upper = ret
        return ast.For(
            target=ast.Name(id=target),
            iter=ast.Call(
                func=ast.Name(id="mrange"),
                args=[lower, upper],
                keywords=[]
            ),
            body=[],
            orelse=[]
        )

    def visitContinue_statement(self, ctx: PlSqlParser.Continue_statementContext):
        ret = self.visitChildren(ctx)
        condition = None if not ctx.condition() else ret[0]
        if not condition:
            return ast.Continue()
        return ast.If(
            test=condition,
            body=[ast.Continue()],
            orelse=[]
        )

    def visitExit_statement(self, ctx: PlSqlParser.Exit_statementContext):
        ret = self.visitChildren(ctx)
        condition = None if not ctx.condition() else ret[0]
        if not condition:
            return ast.Break()
        return ast.If(
            test=condition,
            body=[ast.Break()],
            orelse=[]
        )

    def visitAssignment_statement(self, ctx: PlSqlParser.Assignment_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        name = ret.popleft()
        value = None if not ret else ret[0]
        if isinstance(name, ast.Call):
            # this is not really a function call, let's find what is
            if name.args:
                # this is a table pl being filled
                # ie: tbObjects(1) := 1
                name = ast.Subscript(
                    value=name.func,
                    slice=ast.Index(value=name.args[0])
                )
            else:
                # this is a call for value. so we remove the call
                # ie: x() <<= 1 => x <<= 1
                name = name.func
        return ast.AugAssign(
            target=name,
            value=value,
            op=ast.LShift()
        )

    def visitSimple_case_statement(self, ctx: PlSqlParser.Simple_case_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        # ret is something like [expr, ELIF, expr, exprs, ELIF, expr, exprs, ELSE exprs]
        case_item = ret.popleft() # the value to compare
        for i, item in enumerate(ret):
            if isinstance(item, ELIF):
                value = ret[i + 1]
                ret[i + 1] = ast.BinOp(
                    left=case_item,
                    op=ast.Eq(),
                    right=value
                )
        ret.popleft() # delete the first ELIF token
        return self.processIf_children(ret)

    def visitSearched_case_statement(self, ctx: PlSqlParser.Searched_case_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        # ret is something like [ELIF, exprs, ELIF, exprs, ELSE exprs]
        ret.popleft() # delete the first ELIF token
        return self.processIf_children(ret)

    def visitIf_statement(self, ctx: PlSqlParser.If_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        return self.processIf_children(ret)

    def processIf_children(self, children: list):
        ret = children
        test = None
        body = []
        orelse = []
        while ret:
            test = ret.pop()
            if isinstance(test, ELSE):
                orelse = body
                body = []
            elif isinstance(test, ELIF):
                orelse = [ast.If(
                    test=body[0],
                    body=body[1:],
                    orelse=orelse
                )]
                body = []
            else:
                body = [test] + body
        return ast.If(
            test=test,
            body=body[1:],
            orelse=orelse
        )

    def visitElsif_part(self, ctx: PlSqlParser.Elsif_partContext):
        ret = self.visitChildren(ctx)
        return [ELIF()] + ret

    def visitElse_part(self, ctx: PlSqlParser.Else_partContext):
        ret = self.visitChildren(ctx)
        return [ELSE()] + ret

    def visitSimple_case_when_part(self, ctx: PlSqlParser.Simple_case_when_partContext):
        ret = self.visitChildren(ctx)
        return [ELIF()] + ret

    def visitSearched_case_when_part(self, ctx: PlSqlParser.Searched_case_when_partContext):
        ret = self.visitChildren(ctx)
        return [ELIF()] + ret

    def visitCase_else_part(self, ctx: PlSqlParser.Case_else_partContext):
        ret = self.visitChildren(ctx)
        return [ELSE()] + ret

    def visitExecute_immediate(self, ctx: PlSqlParser.Execute_immediateContext):
        if ctx.using_clause() or ctx.dynamic_returning_clause():
            raise NotImplementedError(f"unimplemented Execute_immediate {ctx.getText()}")
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        sql = ret.popleft()
        return ast.Call(
            func=ast.Name(id="execute_immediate_into"),
            args=[sql] + list(ret),
            keywords=[]
        )

    def visitFunction_call(self, ctx: PlSqlParser.Function_callContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        routine_name = ret.popleft()
        args = ret
        return ast.Call(
            func=routine_name,
            args=args,
            keywords=[]
        )

    def visitRoutine_name(self, ctx: PlSqlParser.Routine_nameContext):
        ret = self.visitChildren(ctx)
        pkg = ret[0]
        method = None if len(ret) < 2 else ret[1]
        pkg = self.wrap_local_variable(pkg.id)
        self.add_object_to_imports(pkg)
        if not method:
            return pkg
        return ast.Attribute(
            value=pkg,
            attr=method
        )

    def visitSeq_of_declare_specs(self, ctx: PlSqlParser.Seq_of_declare_specsContext):
        ret = self.visitChildren(ctx)
        declared_vars = []
        for expr in ret:
            if isinstance(expr, ast.Assign):
                declared_vars.append(expr.targets[0].id)
            elif isinstance(expr, ast.FunctionDef):
                declared_vars.append(expr.name)
        add_no_repeat(self.vars_declared, declared_vars)
        return ret

    def visitCursor_declaration(self, ctx: PlSqlParser.Cursor_declarationContext):
        cursor_params = [
            self.visitChildren(param)[0].id
            for param in ctx.parameter_spec()
        ]
        visitor = ScriptVisitor()
        visitor.vars_declared = self.vars_declared + cursor_params
        ret = visitor.visitChildren(ctx)
        ret = deque(ret)
        name: ast.Name = ret.popleft()
        sql: SQL = None
        sql_vars = []
        for param in list(ret):
            if isinstance(param, SQL):
                sql = param
            elif isinstance(param, SQL_VAR):
                sql_var = ast.Str(s=param.varname)
                sql_vars.append(sql_var)
            else:
                continue
            ret.remove(param)
        cursor_params = [ast.Str(i) for i in cursor_params]
        add_no_repeat(self.vars_declared, name.id)
        return ast.Assign(
            targets=[name],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=PKG_PLCURSOR),
                    attr="CURSOR"
                ),
                args=[
                    ast.Str(sql.sql),
                    ast.List(elts=sql_vars),
                    ast.List(elts=cursor_params)
                ],
                keywords=[]
            )
        )

    def visitData_manipulation_language_statements(self, ctx: PlSqlParser.Data_manipulation_language_statementsContext):
        visitor = SqlVisitor()
        visitor.vars_declared = self.vars_declared
        return visitor.visitData_manipulation_language_statements(ctx)

    def visitSelect_statement(self, ctx: PlSqlParser.Select_statementContext):
        visitor = SqlVisitor()
        visitor.vars_declared = self.vars_declared
        return visitor.visitSelect_statement(ctx)

    def visitOpen_statement(self, ctx: PlSqlParser.Open_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        cursor_call = ret.popleft()
        cursor_call_args = cursor_call.args
        cursor_call.args = []
        return ast.Call(
            func=ast.Attribute(
                value=cursor_call,
                attr="OPEN"
            ),
            args=[
                ast.List(elts=cursor_call_args),
                ast.Call(
                    func=ast.Name(id="locals"),
                    args=[],
                    keywords=[]
                )
            ],
            keywords=[]
        )

    def visitFetch_statement(self, ctx: PlSqlParser.Fetch_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        cursor = ret.popleft()
        destinations = ret
        return ast.Call(
            func=ast.Attribute(
                value=cursor,
                attr="FETCH"
            ),
            args=destinations,
            keywords=[]
        )

    def visitClose_statement(self, ctx: PlSqlParser.Close_statementContext):
        ret = self.visitChildren(ctx)
        cursor = ret[0]
        return ast.Call(
            func=ast.Attribute(
                value=cursor,
                attr="CLOSE"
            ),
            args=[],
            keywords=[]
        )

    def visitVariable_declaration(self, ctx: PlSqlParser.Variable_declarationContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        name: ast.Name = ret.popleft()
        value = ast.Call(
            func=ast.Name(id="m"),
            args=[],
            keywords=[]
        )
        add_no_repeat(self.vars_declared, name.id)
        if ret and isinstance(ret[0], TYPE):
            the_type = ret.popleft().the_type
            value = ast.Call(
                func=the_type,
                args=[],
                keywords=[]
            )
        if ret:
            value = ret.popleft()
        return ast.Assign(
            targets=[name],
            value=value
        )

    def visitReturn_statement(self, ctx: PlSqlParser.Return_statementContext):
        ret = self.visitChildren(ctx)
        value = None if not ret else ret[0]
        return ast.Return(value=value)

    def visitConcatenation(self, ctx: PlSqlParser.ConcatenationContext):
        operands = self.visitChildren(ctx)
        if len(ctx.BAR()) == 2:
            return ast.Call(
                func=ast.Name(id="CONCAT"),
                args=operands,
                keywords=[]
            )
        elif len(operands) == 2:
            left, right = operands
            operator = OPERATORS[ctx.op.text]()
            return ast.BinOp(
                left=left,
                op=operator,
                right=right
            )
        elif len(operands) == 1:
            return operands
        else:
            raise NotImplementedError(f"unimplemented Concatenation: {ctx.getText()}")

    def visitRelational_expression(self, ctx: PlSqlParser.Relational_expressionContext):
        expr = self.visitChildren(ctx)
        if len(expr) == 3:
            left, operator, right = expr
            return ast.Compare(
                left=left,
                ops=[operator],
                comparators=[right]
            )
        return expr[0]

    def visitLogical_expression(self, ctx: PlSqlParser.Logical_expressionContext):
        ret = self.visitChildren(ctx)
        expr = ret[0]
        if ctx.IS() and ctx.NULL():
            expr = ast.Call(
                func=ast.Name(id="ISNULL"),
                args=[expr],
                keywords=[]
            )
        if ctx.NOT():
            expr = ast.Call(
                func=ast.Name(id="NOT"),
                args=[expr],
                keywords=[]
            )
        if len(ret) == 1:
            return expr
        operator = None
        if ctx.AND():
            operator = ast.And()
        elif ctx.OR():
            operator = ast.Or()
        else:
            raise NotImplementedError(f"unsupported operator: {ctx.getText()}")
        return ast.BoolOp(
            op=operator,
            values=ret
        )

    def visitSubtype_declaration(self, ctx: PlSqlParser.Subtype_declarationContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        type_name: ast.Name = ret.popleft()
        the_type: TYPE = ret.popleft()
        return ast.Assign(
            targets=[type_name],
            value=the_type.the_type
        )

    def visitType_declaration(self, ctx: PlSqlParser.Type_declarationContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        type_name = ret.popleft()
        targets = [type_name]
        add_no_repeat(self.vars_declared, type_name.id)
        if ctx.table_type_def():
            value = ast.Name(id=TYPE_PLTABLE)
            if ret and isinstance(ret[0], TYPE):
                the_type = ret.popleft()
                the_type = the_type.the_type
                value = ast.Call(
                    func=ast.Name(id=TYPE_PLTABLE_OF),
                    args=[the_type],
                    keywords=[]
                )
                add_no_repeat(self.pkgs_calls_found, TYPE_PLRECORD)
            add_no_repeat(self.pkgs_calls_found, TYPE_PLTABLE)
            return ast.Assign(
                targets=targets,
                value=value
            )
        if ctx.record_type_def():
            add_no_repeat(self.pkgs_calls_found, TYPE_PLRECORD)
            return ast.Assign(
                targets=targets,
                value=ast.Name(id=TYPE_PLRECORD)
            )
        raise NotImplementedError(f"unsupported Type_declaration: {ret}")

    def visitField_spec(self, ctx: PlSqlParser.Field_specContext):
        # we don't care about the fields in the records
        return None

    def visitType_spec(self, ctx: PlSqlParser.Type_specContext):
        if ctx.PERCENT_TYPE():
            return None
        elif ctx.PERCENT_ROWTYPE():
            add_no_repeat(self.pkgs_calls_found, TYPE_PLRECORD)
            return TYPE(ast.Name(id=TYPE_PLRECORD))
        elif ctx.type_name():
            type_name = self.visitChildren(ctx)[0]
            return TYPE(type_name)
        return None

    def visitType_name(self, ctx: PlSqlParser.Type_nameContext):
        value = self.wrap_id_expressions(ctx.id_expression())
        return value

    def visitRelational_operator(self, ctx: PlSqlParser.Relational_operatorContext):
        text = ctx.getText()
        operator = OPERATORS[text]
        return operator()

    def visitString_function(self, ctx: PlSqlParser.String_functionContext):
        ret = self.visitChildren(ctx)
        call = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=PKG_PLGLOBALS),
                attr=None
            ),
            args=ret,
            keywords=[]
        )
        if ctx.SUBSTR():
            call.func.attr = "SUBSTR"
        elif ctx.NVL():
            call.func.attr = "NVL"
        elif ctx.TO_CHAR():
            call.func.attr = "TO_CHAR"
        elif ctx.TRIM():
            call.func.attr = "TRIM"
        else:
            raise NotImplementedError(f"unimplemented String_function {ctx.getText()}")
        return call

    def visitOther_function(self, ctx: PlSqlParser.Other_functionContext):
        ret = self.visitChildren(ctx)
        cursor = ret[0]
        attr = None
        if ctx.PERCENT_ISOPEN():
            attr = "ISOPEN"
        elif ctx.PERCENT_ROWCOUNT():
            attr = "ROWCOUNT"
        elif ctx.PERCENT_FOUND():
            attr = "FOUND"
        elif ctx.PERCENT_NOTFOUND():
            attr = "NOTFOUND"
        return ast.Call(
            func=ast.Attribute(
                value=cursor,
                attr=attr
            ),
            args=[],
            keywords=[]
        )

    def visitGeneral_element(self, ctx: PlSqlParser.General_elementContext):
        ret = self.visitChildren(ctx)
        ret = deque(ret)
        value = ret.popleft()
        self.add_object_to_imports(value)
        if not ret:
            return value
        # ie: tbmessages(nuidx).id
        attr = ret.popleft()
        if isinstance(attr, ast.Call):
            attr = attr.func.id
        else:
            raise NotImplementedError(f"unsupported General_element {attr}")
        value = ast.Attribute(
            value=value,
            attr=attr
        )
        return value

    def add_object_to_imports(self, the_object):
        name = the_object
        while True:
            if isinstance(name, str):
                if name != self.pkg_name and name not in self.vars_declared:
                    add_no_repeat(self.pkgs_calls_found, name)
                break
            elif isinstance(name, ast.Call):
                name = name.func
            elif isinstance(name, ast.Attribute):
                name = name.value
            elif isinstance(name, ast.Name):
                name = name.id
            else:
                raise NotImplementedError(f"unsupported object to import {name}")

    def visitGeneral_element_part(self, ctx: PlSqlParser.General_element_partContext):
        ret = self.visitChildren(ctx)
        id_expressions = ctx.id_expression()
        value = self.wrap_id_expressions(id_expressions.copy())
        ret = ret[len(id_expressions):] # leave only the function parameters in ret
        args = None
        if ctx.function_argument():
            args = ctx.function_argument().argument()
            if not args:
                args = []
        if args is not None:
            # ie: some_function(1,2,3)
            args = ret # the remaining values should be the function arguments
            return ast.Call(
                func=value,
                args=args,
                keywords=[]
            )
        # we don't know if it is a function call or a value :/
        # so, we call the value
        # ie: x => x()
        return ast.Call(
            func=value,
            args=[],
            keywords=[]
        )

    def wrap_id_expressions(self, id_expressions: list):
        id_expressions = [item.getText() for item in id_expressions]
        value = self.wrap_recursive_properties(id_expressions)
        return value

    def wrap_recursive_properties(self, recursive_props: List[str]):
        '''converts a.b.c in ast.Attr(a, ast.Attr(b, ast.Attr(c)))'''
        recursive_props = deque(recursive_props)
        value = recursive_props.popleft().upper()
        value = self.wrap_local_variable(value)
        while recursive_props:
            member = recursive_props.popleft().upper()
            value = ast.Attribute(
                value=value,
                attr=member
            )
        return value

    def wrap_local_variable(self, value: str):
        if value in self.vars_declared or value == self.pkg_name:
            # ie: x := y
            value = ast.Name(id=value)
        elif value in self.vars_in_package:
            # ie: convert x := 1 en pkgtest.x := 1
            value = ast.Attribute(
                value=ast.Name(id=self.pkg_name),
                attr=value
            )
        elif value in dir(PLGLOBALS):
            value = ast.Attribute(
                value=ast.Name(id=PKG_PLGLOBALS),
                attr=value
            )
        else:
            # ie: x := pkg.method()
            value = ast.Name(id=value)
        return value

    def visitRegular_id(self, ctx: PlSqlParser.Regular_idContext):
        if not ctx.REGULAR_ID():
            the_id = ctx.getText().upper()
        else:
            the_id = ctx.REGULAR_ID().getText().upper()
        return ast.Name(id=the_id)

    def visitUnary_expression(self, ctx: PlSqlParser.Unary_expressionContext):
        ret = self.visitChildren(ctx)
        value = ret[0]
        sign = ctx.children[0].getText()
        if sign == "-":
            return ast.UnaryOp(
                op=ast.USub(),
                operand=value
            )
        return ret

    def visitConstant(self, ctx: PlSqlParser.ConstantContext):
        value = None
        if ctx.TRUE():
            value = ast.NameConstant(value=True)
        elif ctx.FALSE():
            value = ast.NameConstant(value=False)
        elif ctx.NULL():
            value = ast.Call(
                func=ast.Name(id="NULL"),
                args=[],
                keywords=[]
            )
        if value:
            return self.make_mutable(value)
        return self.visitChildren(ctx)

    def visitNull_statement(self, ctx: PlSqlParser.Null_statementContext):
        return ast.Pass()

    def visitNumeric(self, ctx: PlSqlParser.NumericContext):
        text = ctx.getText()
        num = PLGLOBALS.TO_NUMBER(text).value
        return self.make_mutable(ast.Num(n=num))

    def visitQuoted_string(self, ctx: PlSqlParser.Quoted_stringContext):
        str_value: str = ctx.CHAR_STRING().getText()[1:-1]
        str_value = str_value.replace("''", "'")
        ret = self.make_mutable(ast.Str(str_value))
        return ret
