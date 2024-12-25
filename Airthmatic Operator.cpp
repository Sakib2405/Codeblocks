#include<iostream>
#include<conio.h>
using namespace std;

int main()

{
    int num1,num2;
    cout<<"Enter two number: "<<endl ;

    cin>> num1>> num2;

    int sum= num1+num2;

    cout<<endl <<endl<<"\t" <<"Sumation is: " << sum <<endl<<endl;

        int sub= num1-num2;

    cout<<"\t" <<"Subtraction is: " << sub <<endl<<endl;

    int mul= num1*num2;
    cout<<"\t"<<"Multiplication is: "<<mul <<endl <<"\n";

    float div= (float)num1/num2;
    cout<<"\t" <<"Division is: "<<div <<endl<<"\n";

    int rem=num1%num2;
    cout<<"\t" <<"Reminder is: "<<rem <<endl<<endl;



    getch();

}
