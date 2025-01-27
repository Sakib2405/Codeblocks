#include<iostream>
#include<conio.h>
using namespace std;

int main()

{
    int  A[2][3];

    cout<<"Enter the elements of matrix: "<<endl;
    for(int i=0; i<2; i++)
    {
        for(int j=0; j<3; j++)
        {
            cout<<"A("<<i+1<<","<<j+1<<") = ";

            cin>>A[i][j];
        }
        cout<<endl;
    }

      cout<<"The matrix form is: "<<endl;
     for(int i=0; i<2; i++)
    {
        for(int j=0; j<3; j++)
        {
            cout<<"  "<<A[i][j];
        }
        cout<<endl;
    }
    getch();
}

